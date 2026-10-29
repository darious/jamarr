"""UPnP event (GENA) subscriptions for renderers being played to.

The playback monitor holds a renderer while it runs (``acquire`` /
``release``). For a held renderer this module subscribes to the AVTransport
and RenderingControl services, so ``LastChange`` events push transport state,
the current TrackURI, volume and mute instead of the monitor discovering them
by polling every second. Polling does not go away: position is never evented,
and plenty of renderers event badly, so the monitor keeps a slower watchdog
poll while events are healthy and drops back to 1 s polling when they are not.

Health is tracked per service. A subscription is healthy once the SUBSCRIBE
was accepted *and* the device's initial NOTIFY arrived (it proves the device
can reach our callback server), it has not expired, and the watchdog polls
have not caught it missing changes. Renewal happens before expiry; a renderer
rebirth (discovery re-hydrated it into a new DmrDevice, e.g. a new BOOTID) or a
change of our own LAN address re-subscribes from scratch. ``supports_events``
on the renderer is only set once events have actually arrived, and cleared
when the device refuses or keeps breaking them.

There is exactly one callback server for all of it: async_upnp_client's
``AiohttpNotifyServer``, bound to the same source address UPnP uses
(``UPnPManager.local_ip``) on ``renderer.upnp_event_port`` (env
``UPNP_EVENT_PORT``, default 8113).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Callable, Optional

from async_upnp_client.exceptions import UpnpConnectionError, UpnpError, UpnpResponseError

from app.services.upnp.staging import same_media_uri

logger = logging.getLogger(__name__)

# Services subscribed to, by DmrDevice abbreviation -> name used in diagnostics.
SERVICES = {"AVT": "AVTransport", "RC": "RenderingControl"}

# Requested subscription lifetime; devices may grant less (or more).
SUBSCRIBE_TIMEOUT_S = 1800
# Renew this long before expiry (or at half the lifetime, if that is shorter).
RENEW_MARGIN_S = 60.0
# Bound on one SUBSCRIBE/UNSUBSCRIBE round trip.
SUBSCRIBE_CALL_TIMEOUT_S = 8.0
# The device must send its initial NOTIFY this soon after SUBSCRIBE; if it does
# not, it cannot reach our callback (firewall, wrong interface) or does not
# event at all.
INITIAL_EVENT_TIMEOUT_S = 10.0
# A watchdog poll that disagrees with an event older than this means the
# device did not event a change.
EVENT_SETTLE_S = 2.0
# Missed changes in a row before a service counts as unreliable (and is
# re-subscribed); unreliable episodes before eventing is given up for the
# renderer (until it is reborn or Jamarr restarts).
MAX_MISMATCHES = 2
MAX_UNRELIABLE_EPISODES = 3
# Consecutive SUBSCRIBE failures before giving up on a service.
MAX_SUBSCRIBE_FAILURES = 6
# Retry delays after failed subscribes (seconds), last one repeats.
RETRY_BACKOFF_S = (5.0, 15.0, 30.0, 60.0, 120.0)
# Keep subscriptions this long after the monitor lets go (pause, track change).
RELEASE_LINGER_S = 120.0
# Nothing due: how long the per-renderer task sleeps before looking again.
IDLE_CHECK_S = 60.0

_IGNORED_VALUES = {"", "NOT_IMPLEMENTED"}


def parse_upnp_duration(value: Any) -> Optional[float]:
    """``H+:MM:SS[.F+]`` (UPnP time) to seconds; None when absent/unknown."""
    if value is None:
        return None
    text = str(value).strip()
    if text in _IGNORED_VALUES:
        return None
    try:
        parts = text.split(":")
        if len(parts) != 3:
            return None
        hours, minutes = int(parts[0]), int(parts[1])
        seconds = float(parts[2].split("/")[0])
        return hours * 3600 + minutes * 60 + seconds
    except ValueError:
        return None


def _clean(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return None if text in _IGNORED_VALUES else text


def _same_state(a: Optional[str], b: Optional[str]) -> bool:
    """Transport states equal for watchdog purposes (TRANSITIONING ~ PLAYING)."""
    norm = {"TRANSITIONING": "PLAYING"}
    return norm.get(a or "", a) == norm.get(b or "", b)


@dataclass
class ServiceSubscription:
    key: str  # "AVT" / "RC"
    sid: Optional[str] = None
    subscribed: bool = False
    subscribed_at: Optional[float] = None  # monotonic, last fresh SUBSCRIBE
    expires_at: Optional[float] = None
    renew_at: Optional[float] = None
    timeout_s: Optional[float] = None
    awaiting_initial: bool = False
    events: int = 0
    last_event_at: Optional[float] = None  # monotonic
    last_event_wall: Optional[float] = None
    renewals: int = 0
    failures: int = 0  # consecutive
    total_failures: int = 0
    last_error: Optional[str] = None
    retry_at: float = 0.0
    unsupported: Optional[str] = None  # no such service / no eventSubURL
    gave_up: Optional[str] = None
    mismatches: int = 0
    unreliable: Optional[str] = None

    def healthy(self, now: float) -> bool:
        return bool(
            self.subscribed
            and not self.awaiting_initial
            and not self.unreliable
            and self.expires_at is not None
            and now < self.expires_at
        )

    def reset(self) -> None:
        self.sid = None
        self.subscribed = False
        self.expires_at = None
        self.renew_at = None
        self.awaiting_initial = False
        self.mismatches = 0


@dataclass(frozen=True)
class EventSnapshot:
    """What the renderer last told us by event (plus watchdog corrections)."""

    transport_state: Optional[str]
    track_uri: Optional[str]
    track_duration: Optional[float]
    volume: Optional[int]
    muted: Optional[bool]
    generation: int
    avt_healthy: bool
    rc_healthy: bool


@dataclass
class RendererEvents:
    udn: str
    services: dict[str, ServiceSubscription] = field(
        default_factory=lambda: {key: ServiceSubscription(key) for key in SERVICES}
    )
    # The DmrDevice subscribed through; a different one means the renderer
    # was reborn.
    dmr: Any = None
    server_generation: int = -1
    holders: int = 0
    active: bool = False
    task: Optional[asyncio.Task] = None
    release_task: Optional[asyncio.Task] = None
    kick: asyncio.Event = field(default_factory=asyncio.Event)
    wake: asyncio.Event = field(default_factory=asyncio.Event)
    # Event-derived state.
    transport_state: Optional[str] = None
    track_uri: Optional[str] = None
    av_transport_uri: Optional[str] = None
    track_duration: Optional[float] = None
    volume: Optional[int] = None
    # Bumped per Volume event; only the newest event's read-back is applied.
    volume_seq: int = 0
    muted: Optional[bool] = None
    # Wall clock (time.time) of the Mute event, to weigh it against a mute
    # Jamarr set itself (player.globals.renderer_muted_at).
    muted_at: Optional[float] = None
    generation: int = 0
    unreliable_episodes: int = 0
    disabled: Optional[str] = None
    in_notify: bool = False


def _default_server_factory(requester, source):
    from async_upnp_client.aiohttp import AiohttpNotifyServer

    return AiohttpNotifyServer(requester, source)


class UpnpEventManager:
    def __init__(
        self,
        manager,
        *,
        server_factory: Optional[Callable[[Any, tuple[str, int]], Any]] = None,
        clock: Callable[[], float] = time.monotonic,
        config: Optional[dict] = None,
    ) -> None:
        self.manager = manager
        self._server_factory = server_factory or _default_server_factory
        self._clock = clock
        self._config = config
        self._server = None
        self._bound_ip: Optional[str] = None
        self._server_error: Optional[str] = None
        self._server_failures = 0
        self._server_generation = 0
        self._server_lock: Optional[asyncio.Lock] = None
        self._renderers: dict[str, RendererEvents] = {}
        # udn -> whether events proved usable (True) or not (False) this run.
        self._verdicts: dict[str, bool] = {}
        self._bg_tasks: set[asyncio.Task] = set()
        self._stopping = False

    # ---------------------------------------------------------------- config

    def _settings(self) -> dict:
        if self._config is not None:
            return self._config
        try:
            from app.config import get_upnp_event_config

            return get_upnp_event_config()
        except Exception:
            logger.debug("Could not read UPnP event config", exc_info=True)
            return {"enabled": True, "port": 8113}

    @property
    def enabled(self) -> bool:
        return bool(self._settings().get("enabled", True))

    # -------------------------------------------------------------- lifetime

    def acquire(self, udn: str) -> None:
        """The monitor is driving udn: keep it subscribed. Never blocks."""
        if self._stopping or not self.enabled:
            return
        st = self._renderers.get(udn)
        if st is None:
            st = self._renderers[udn] = RendererEvents(udn)
        st.holders += 1
        if st.release_task is not None and not st.release_task.done():
            st.release_task.cancel()
        st.release_task = None
        st.active = True
        if st.task is None or st.task.done():
            st.task = asyncio.create_task(self._run(st), name=f"upnp-events:{udn}")
        else:
            st.kick.set()

    def release(self, udn: str, linger: Optional[float] = None) -> None:
        """The monitor stopped; unsubscribe after ``linger`` unless re-acquired."""
        st = self._renderers.get(udn)
        if st is None:
            return
        st.holders = max(0, st.holders - 1)
        if st.holders or not st.active:
            return
        delay = RELEASE_LINGER_S if linger is None else linger
        if st.release_task is not None and not st.release_task.done():
            st.release_task.cancel()
        st.release_task = asyncio.create_task(self._linger_then_drop(st, delay))

    async def _linger_then_drop(self, st: RendererEvents, delay: float) -> None:
        if delay > 0:
            await asyncio.sleep(delay)
        if st.holders == 0:
            st.release_task = None  # don't cancel ourselves in drop()
            await self.drop(st.udn)

    async def drop(self, udn: str) -> None:
        """Unsubscribe udn now (stop, renderer switch, shutdown)."""
        st = self._renderers.get(udn)
        if st is None:
            return
        st.holders = 0
        st.active = False
        for task in (st.task, st.release_task):
            if task is not None and not task.done() and task is not asyncio.current_task():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
        st.task = None
        st.release_task = None
        await self._teardown(st, unsubscribe=True)
        logger.info("[UPnP events] Unsubscribed from %s", udn)

    async def stop(self) -> None:
        """Shutdown: unsubscribe everything and stop the callback server."""
        self._stopping = True
        for udn in list(self._renderers):
            try:
                await self.drop(udn)
            except Exception:
                logger.debug("Dropping event subscriptions failed for %s", udn, exc_info=True)
        await self._stop_server()
        for task in list(self._bg_tasks):
            task.cancel()
        self._stopping = False

    def check(self, udn: str) -> None:
        """Cheap per-poll check: re-subscribe after rebirth or address change."""
        st = self._renderers.get(udn)
        if st is None or not st.active:
            return
        dmr = self._device_for(st)
        stale_ip = self._server is not None and self._bound_ip != self.manager.local_ip
        if dmr is not st.dmr or stale_ip:
            st.kick.set()

    # ----------------------------------------------------------------- state

    def snapshot(self, udn: str) -> Optional[EventSnapshot]:
        st = self._renderers.get(udn)
        if st is None:
            return None
        now = self._clock()
        return EventSnapshot(
            transport_state=st.transport_state,
            track_uri=st.track_uri or st.av_transport_uri,
            track_duration=st.track_duration,
            volume=st.volume,
            muted=st.muted,
            generation=st.generation,
            avt_healthy=st.active and st.services["AVT"].healthy(now),
            rc_healthy=st.active and st.services["RC"].healthy(now),
        )

    def avt_healthy(self, udn: str) -> bool:
        snap = self.snapshot(udn)
        return bool(snap and snap.avt_healthy)

    def rc_healthy(self, udn: str) -> bool:
        snap = self.snapshot(udn)
        return bool(snap and snap.rc_healthy)

    def muted(self, udn: str) -> Optional[bool]:
        """Evented mute, only while RenderingControl events are healthy.

        A dropped or unhealthy subscription no longer tells us about mute
        changes, so what it last said is not the device's state any more.
        """
        state = self.muted_state(udn)
        return state[0] if state is not None else None

    def muted_state(self, udn: str) -> Optional[tuple[bool, Optional[float]]]:
        """(muted, wall-clock time it was evented), or None (see ``muted``)."""
        st = self._renderers.get(udn)
        if st is None or st.muted is None:
            return None
        if not (st.active and st.services["RC"].healthy(self._clock())):
            return None
        return st.muted, st.muted_at

    def supports_events(self, udn: str) -> bool:
        """Whether events proved usable on udn in this run (False if unknown)."""
        return bool(self._verdicts.get(udn, False))

    async def wait_for_change(self, udn: str, seen_generation: int, timeout: float) -> bool:
        """Sleep up to ``timeout``; return early (True) on an AVTransport change."""
        st = self._renderers.get(udn)
        if st is None:
            await asyncio.sleep(timeout)
            return False
        if st.generation != seen_generation:
            return True
        st.wake.clear()
        try:
            await asyncio.wait_for(st.wake.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    def note_poll(
        self,
        udn: str,
        transport_state: Optional[str] = None,
        track_uri: Optional[str] = None,
    ) -> bool:
        """Reconcile a watchdog poll against the event-derived state.

        A poll that disagrees with state last evented more than
        ``EVENT_SETTLE_S`` ago means the device did not event a change. The
        polled values win (they are fresher); repeated misses mark the
        AVTransport subscription unreliable, which drops the monitor back to
        1 s polling and re-subscribes. Returns True on a mismatch.
        """
        st = self._renderers.get(udn)
        if st is None or not st.active:
            return False
        sub = st.services["AVT"]
        now = self._clock()
        if not sub.healthy(now):
            return False
        if sub.last_event_at is not None and now - sub.last_event_at < EVENT_SETTLE_S:
            return False
        polled_state = _clean(transport_state)
        polled_state = polled_state.upper() if polled_state else None
        polled_uri = _clean(track_uri)
        current_uri = st.track_uri or st.av_transport_uri
        mismatch = []
        if polled_state and st.transport_state and not _same_state(
            polled_state, st.transport_state
        ):
            mismatch.append(f"state {st.transport_state} vs polled {polled_state}")
        if polled_uri and current_uri and not same_media_uri(polled_uri, current_uri):
            mismatch.append("TrackURI changed without an event")
        if not mismatch:
            sub.mismatches = 0
            return False
        # Adopt the polled truth so the snapshot is right from here on.
        if polled_state and not _same_state(polled_state, st.transport_state):
            st.transport_state = polled_state
        if polled_uri and not same_media_uri(polled_uri, current_uri):
            st.track_uri = polled_uri
        st.generation += 1
        sub.mismatches += 1
        logger.info(
            "[UPnP events] %s: watchdog poll disagrees with events (%s, %d in a row)",
            udn,
            "; ".join(mismatch),
            sub.mismatches,
        )
        if sub.mismatches >= MAX_MISMATCHES:
            self._mark_unreliable(st, "AVT", "events missed changes seen by polling")
        return True

    def _mark_unreliable(self, st: RendererEvents, key: str, reason: str) -> None:
        sub = st.services[key]
        if sub.unreliable:
            return
        sub.unreliable = reason
        st.unreliable_episodes += 1
        logger.warning(
            "[UPnP events] %s %s unreliable: %s; polling and re-subscribing",
            st.udn,
            SERVICES.get(key, key),
            reason,
        )
        if st.unreliable_episodes >= MAX_UNRELIABLE_EPISODES:
            st.disabled = f"{reason} ({st.unreliable_episodes} times)"
            logger.warning(
                "[UPnP events] Giving up on events for %s: %s", st.udn, st.disabled
            )
            self._set_verdict(st.udn, False)
        st.kick.set()

    # ----------------------------------------------------------- event input

    def _service_callback(self, st: RendererEvents, key: str, dmr):
        def on_event(service, state_variables) -> None:
            if st.dmr is not dmr:
                return  # a reborn renderer's old services
            outer = not st.in_notify
            if outer:
                sub = st.services[key]
                now = self._clock()
                sub.events += 1
                sub.last_event_at = now
                sub.last_event_wall = time.time()
                if sub.awaiting_initial:
                    sub.awaiting_initial = False
                    if key == "AVT" and sub.subscribed:
                        self._set_verdict(st.udn, True)
            try:
                self._apply(st, key, dmr, state_variables)
            except Exception:
                logger.debug("Applying UPnP event failed for %s", st.udn, exc_info=True)
            # Let DmrDevice expand LastChange (it re-enters this callback with
            # the individual variables) and keep its own state current.
            if outer:
                st.in_notify = True
            try:
                dmr._on_event(service, state_variables)
            except Exception:
                logger.debug("DmrDevice event handling failed for %s", st.udn, exc_info=True)
            finally:
                if outer:
                    st.in_notify = False

        return on_event

    def _apply(self, st: RendererEvents, key: str, dmr, state_variables) -> None:
        changed = False
        for var in state_variables or ():
            name = getattr(var, "name", None)
            value = getattr(var, "value", None)
            if key == "AVT":
                if name == "TransportState":
                    new = _clean(value)
                    new = new.upper() if new else None
                    if new and new != st.transport_state:
                        st.transport_state = new
                        changed = True
                elif name == "CurrentTrackURI":
                    new = _clean(value)
                    if new != st.track_uri:
                        st.track_uri = new
                        changed = True
                elif name == "AVTransportURI":
                    new = _clean(value)
                    if new != st.av_transport_uri:
                        st.av_transport_uri = new
                        changed = changed or not st.track_uri
                elif name == "CurrentTrackDuration":
                    st.track_duration = parse_upnp_duration(value)
            elif key == "RC":
                if name == "Volume" and value is not None:
                    percent = self._volume_percent(var, value)
                    if percent is None:
                        continue
                    getter = getattr(self.manager, "get_volume", None)
                    if getter is None:
                        self._set_volume(st, percent)
                    else:
                        st.volume_seq += 1
                        self._spawn(self._confirm_volume(st, getter, percent, st.volume_seq))
                elif name == "Mute" and value is not None:
                    if isinstance(value, str):
                        muted = value.strip().lower() in ("1", "true", "yes")
                    else:
                        muted = bool(value)
                    st.muted = muted
                    st.muted_at = time.time()
        if changed:
            st.generation += 1
            st.wake.set()

    def _set_volume(self, st: RendererEvents, percent: int) -> None:
        if percent != st.volume:
            st.volume = percent
            self._spawn(self._persist_volume(st.udn, percent))

    async def _confirm_volume(self, st: RendererEvents, getter, evented: int, seq: int) -> None:
        """A Volume event says the volume changed; GetVolume says what it is.

        Some renderers event a value that disagrees with their own GetVolume
        (the Sony XR-65X90J events 6 while GetVolume and the TV's own display
        say 2), so the event is only trusted when the read-back fails.
        """
        try:
            percent = await getter(st.udn)
        except Exception:
            logger.debug("Volume read-back failed for %s", st.udn, exc_info=True)
            percent = None
        if seq != st.volume_seq:
            return  # a newer Volume event's read-back owns the value
        if percent is None:
            percent = evented
        elif percent != evented:
            logger.info(
                "[UPnP events] %s evented volume %s but reads back %s; using %s",
                st.udn, evented, percent, percent,
            )
        self._set_volume(st, int(percent))

    @staticmethod
    def _volume_percent(var, value) -> Optional[int]:
        try:
            current = int(value)
        except (TypeError, ValueError):
            return None
        max_volume = 100
        try:
            if var.max_value:
                max_volume = int(var.max_value) or 100
        except Exception:
            pass
        return max(0, min(100, round(current * 100 / max_volume)))

    # ------------------------------------------------------- subscriptions

    async def _run(self, st: RendererEvents) -> None:
        while st.active and not self._stopping:
            try:
                delay = await self._step(st)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("[UPnP events] Subscription upkeep failed for %s", st.udn)
                delay = 30.0
            try:
                await asyncio.wait_for(st.kick.wait(), timeout=max(0.05, delay))
            except asyncio.TimeoutError:
                pass

    async def _step(self, st: RendererEvents) -> float:
        """One round of subscription upkeep; returns seconds until the next."""
        st.kick.clear()
        dmr = self._device_for(st)
        if dmr is None:
            if st.dmr is not None:
                await self._teardown(st, unsubscribe=False)
                st.dmr = None
            return 10.0
        if st.dmr is not None and dmr is not st.dmr:
            logger.info("[UPnP events] %s was re-discovered (reborn); re-subscribing", st.udn)
            await self._teardown(st, unsubscribe=True)
            st.disabled = None
            st.unreliable_episodes = 0
            for sub in st.services.values():
                sub.failures = 0
                sub.retry_at = 0.0
                sub.gave_up = None
                sub.unsupported = None
                sub.unreliable = None
        st.dmr = dmr
        if st.disabled:
            await self._teardown(st, unsubscribe=True)
            return IDLE_CHECK_S
        if not await self._ensure_server():
            steps = RETRY_BACKOFF_S
            return steps[min(self._server_failures, len(steps)) - 1]
        if st.server_generation != self._server_generation:
            # New callback server (first use or our address changed): any
            # subscription from before points at a callback that is gone.
            await self._teardown(st, unsubscribe=False)
            st.server_generation = self._server_generation

        for key, sub in st.services.items():
            if sub.unsupported or sub.gave_up:
                continue
            now = self._clock()
            if sub.subscribed and sub.unreliable:
                await self._unsubscribe_service(st, key)
                sub.retry_at = 0.0
            if sub.subscribed and sub.awaiting_initial and sub.subscribed_at is not None:
                if now - sub.subscribed_at >= INITIAL_EVENT_TIMEOUT_S:
                    await self._unsubscribe_service(st, key)
                    self._note_failure(st, key, "no initial NOTIFY (callback unreachable?)")
                    continue
            if not sub.subscribed:
                if now >= sub.retry_at:
                    await self._subscribe_service(st, key, dmr)
            elif sub.renew_at is not None and now >= sub.renew_at:
                await self._renew_service(st, key)

        now = self._clock()
        due = [now + IDLE_CHECK_S]
        for sub in st.services.values():
            if sub.unsupported or sub.gave_up:
                continue
            if sub.subscribed:
                if sub.renew_at is not None:
                    due.append(sub.renew_at)
                if sub.awaiting_initial and sub.subscribed_at is not None:
                    due.append(sub.subscribed_at + INITIAL_EVENT_TIMEOUT_S)
            else:
                due.append(sub.retry_at)
        return max(0.05, min(due) - now)

    def _schedule_renewal(self, sub: ServiceSubscription, timeout: timedelta, now: float) -> None:
        seconds = timeout.total_seconds() if timeout else float(SUBSCRIBE_TIMEOUT_S)
        sub.timeout_s = seconds
        sub.expires_at = now + seconds
        sub.renew_at = now + max(1.0, seconds - min(RENEW_MARGIN_S, seconds / 2))

    async def _subscribe_service(self, st: RendererEvents, key: str, dmr) -> None:
        sub = st.services[key]
        service = self._service_for(st, key, dmr)
        if service is None or not getattr(service, "event_sub_url", None):
            sub.unsupported = "service not offered" if service is None else "no eventSubURL"
            if key == "AVT":
                self._set_verdict(st.udn, False)
            return
        handler = self._server.event_handler
        service.on_event = self._service_callback(st, key, dmr)
        # Set before the call: the initial NOTIFY can arrive (or be replayed
        # from the handler's backlog) before SUBSCRIBE returns.
        sub.awaiting_initial = True
        sub.subscribed_at = self._clock()
        try:
            sid, timeout = await asyncio.wait_for(
                handler.async_subscribe(service, timeout=timedelta(seconds=SUBSCRIBE_TIMEOUT_S)),
                SUBSCRIBE_CALL_TIMEOUT_S,
            )
        except (UpnpError, asyncio.TimeoutError, OSError) as exc:
            sub.awaiting_initial = False
            self._note_failure(st, key, exc)
            return
        now = self._clock()
        sub.sid = sid
        sub.subscribed = True
        sub.failures = 0
        sub.last_error = None
        sub.unreliable = None
        sub.mismatches = 0
        self._schedule_renewal(sub, timeout, now)
        if not sub.awaiting_initial:
            if key == "AVT":
                self._set_verdict(st.udn, True)
        logger.info(
            "[UPnP events] Subscribed to %s on %s (SID %s, %ss) via %s",
            SERVICES.get(key, key),
            st.udn,
            sid,
            int(sub.timeout_s or 0),
            handler.callback_url,
        )

    async def _renew_service(self, st: RendererEvents, key: str) -> None:
        sub = st.services[key]
        handler = self._server.event_handler
        events_before = sub.events
        old_sid = sub.sid
        try:
            new_sid, timeout = await asyncio.wait_for(
                handler.async_resubscribe(old_sid, timeout=timedelta(seconds=SUBSCRIBE_TIMEOUT_S)),
                SUBSCRIBE_CALL_TIMEOUT_S,
            )
        except (UpnpError, KeyError, asyncio.TimeoutError, OSError) as exc:
            sub.reset()
            self._note_failure(st, key, exc, renewal=True)
            return
        now = self._clock()
        sub.renewals += 1
        if new_sid != old_sid:
            # The device forgot us and a full SUBSCRIBE took its place: it
            # owes us a fresh initial event (unless one already came).
            sub.subscribed_at = now
            if sub.events == events_before:
                sub.awaiting_initial = True
        sub.sid = new_sid
        sub.subscribed = True
        sub.failures = 0
        sub.last_error = None
        self._schedule_renewal(sub, timeout, now)
        logger.debug(
            "[UPnP events] Renewed %s on %s (SID %s)", SERVICES.get(key, key), st.udn, new_sid
        )

    def _note_failure(self, st: RendererEvents, key: str, exc, renewal: bool = False) -> None:
        sub = st.services[key]
        sub.failures += 1
        sub.total_failures += 1
        if isinstance(exc, str):
            sub.last_error = exc
        else:
            sub.last_error = f"{type(exc).__name__}: {exc}".rstrip(": ")
        steps = RETRY_BACKOFF_S
        sub.retry_at = self._clock() + steps[min(sub.failures, len(steps)) - 1]
        logger.warning(
            "[UPnP events] %s %s on %s failed (%d in a row): %s; polling meanwhile",
            "Renewing" if renewal else "Subscribing to",
            SERVICES.get(key, key),
            st.udn,
            sub.failures,
            sub.last_error,
        )
        refused = isinstance(exc, UpnpResponseError)
        if sub.failures >= MAX_SUBSCRIBE_FAILURES:
            sub.gave_up = sub.last_error
            if key == "AVT":
                self._set_verdict(st.udn, False)
        elif key == "AVT" and refused and not self._verdicts.get(st.udn):
            # The device answered and said no: it does not event (for now).
            self._set_verdict(st.udn, False)
        if isinstance(exc, UpnpConnectionError):
            hook = getattr(self.manager, "note_control_failure", None)
            if hook is not None:
                try:
                    hook(st.udn)
                except Exception:
                    pass

    async def _unsubscribe_service(self, st: RendererEvents, key: str) -> None:
        sub = st.services[key]
        sid = sub.sid
        sub.reset()
        if not sid or self._server is None:
            return
        try:
            await asyncio.wait_for(
                self._server.event_handler.async_unsubscribe(sid), SUBSCRIBE_CALL_TIMEOUT_S
            )
        except (UpnpError, KeyError, asyncio.TimeoutError, OSError) as exc:
            logger.debug("Unsubscribing %s from %s failed: %s", sid, st.udn, exc)

    async def _teardown(self, st: RendererEvents, unsubscribe: bool) -> None:
        for key, sub in st.services.items():
            if unsubscribe:
                await self._unsubscribe_service(st, key)
            else:
                sub.reset()
        # Nothing reports mute changes any more; a resubscription's initial
        # event sets it again.
        st.muted = None
        st.muted_at = None

    # ------------------------------------------------------ device lookup

    def _device_for(self, st: RendererEvents) -> Any:
        return self.manager.dmr_devices.get(st.udn)

    @staticmethod
    def _service_for(st: RendererEvents, key: str, device: Any) -> Any:
        return device._service(key)

    # --------------------------------------------------------------- server

    async def _ensure_server(self) -> bool:
        if self._server_lock is None:
            self._server_lock = asyncio.Lock()
        async with self._server_lock:
            ip = self.manager.local_ip
            if self._server is not None and self._bound_ip == ip:
                return True
            if self._server is not None:
                logger.info(
                    "[UPnP events] Local address changed (%s -> %s); moving callback server",
                    self._bound_ip,
                    ip,
                )
                await self._stop_server_locked()
            if not ip or ip.startswith("127."):
                self._server_error = "no LAN address to receive events on"
                self._server_failures += 1
                return False
            port = int(self._settings().get("port", 8113))
            try:
                await self.manager._ensure_session()
                server = self._server_factory(self.manager._requester, (ip, port))
                await server.async_start_server()
            except Exception as exc:
                self._server_failures += 1
                error = f"{type(exc).__name__}: {exc}"
                if error != self._server_error:
                    logger.warning(
                        "[UPnP events] Could not start the event callback server on %s:%s "
                        "(%s); renderers stay on polling",
                        ip,
                        port,
                        error,
                    )
                self._server_error = error
                return False
            self._server = server
            self._bound_ip = ip
            self._server_error = None
            self._server_failures = 0
            self._server_generation += 1
            logger.info("[UPnP events] Listening for NOTIFY at %s", server.callback_url)
            return True

    async def _stop_server(self) -> None:
        if self._server_lock is None:
            self._server_lock = asyncio.Lock()
        async with self._server_lock:
            await self._stop_server_locked()

    async def _stop_server_locked(self) -> None:
        server, self._server = self._server, None
        self._bound_ip = None
        if server is None:
            return
        try:
            # Also unsubscribes whatever the handler still knows.
            await asyncio.wait_for(server.async_stop_server(), timeout=12)
        except Exception:
            logger.debug("Stopping the UPnP event server failed", exc_info=True)

    # ---------------------------------------------------------- persistence

    def _spawn(self, coro) -> None:
        try:
            task = asyncio.get_running_loop().create_task(coro)
        except RuntimeError:
            coro.close()
            return
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    def _set_verdict(self, udn: str, usable: bool) -> None:
        if self._verdicts.get(udn) is usable:
            return
        self._verdicts[udn] = usable
        info = self.manager.renderers.get(udn)
        if info is not None:
            info["supports_events"] = usable
        logger.info("[UPnP events] %s: events %s", udn, "usable" if usable else "not usable")
        self._spawn(self._persist_verdict(udn, usable))

    async def _persist_verdict(self, udn: str, usable: bool) -> None:
        try:
            from app.db import db_conn

            marker = json.dumps({"usable": usable, "at": time.time()})
            async with db_conn() as db:
                await db.execute(
                    """
                    UPDATE renderer
                    SET supports_events = $2,
                        renderer_metadata = COALESCE(renderer_metadata, '{}'::jsonb)
                            || jsonb_build_object('upnp_events', $3::jsonb)
                    WHERE udn = $1
                    """,
                    udn,
                    usable,
                    marker,
                )
        except Exception:
            logger.debug("Persisting event support for %s failed", udn, exc_info=True)

    async def _persist_volume(self, udn: str, percent: int) -> None:
        """A volume change made on the device (remote, another controller)."""
        # Writes run as separate tasks and may finish out of order: always
        # store the latest evented value, not the one this task was made for.
        st = self._renderers.get(udn)
        if st is not None and st.volume is not None:
            percent = st.volume
        try:
            from app.db import db_conn

            async with db_conn() as db:
                await db.execute(
                    """
                    UPDATE renderer_state
                    SET volume = $1, updated_at = NOW()
                    WHERE renderer_udn = $2 AND volume IS DISTINCT FROM $1
                    """,
                    percent,
                    udn,
                )
        except Exception:
            logger.debug("Persisting evented volume for %s failed", udn, exc_info=True)

    # ---------------------------------------------------------- diagnostics

    def diagnostics(self) -> dict[str, Any]:
        now = self._clock()
        settings = self._settings()

        def ago(t: Optional[float]) -> Optional[float]:
            return round(now - t, 1) if t is not None else None

        def until(t: Optional[float]) -> Optional[float]:
            return round(t - now, 1) if t is not None else None

        renderers = {}
        for udn, st in self._renderers.items():
            services = {}
            for key, sub in st.services.items():
                services[SERVICES.get(key, key)] = {
                    "healthy": st.active and sub.healthy(now),
                    "subscribed": sub.subscribed,
                    "sid": sub.sid,
                    "awaiting_initial_event": sub.awaiting_initial,
                    "timeout_seconds": sub.timeout_s,
                    "expires_in_seconds": until(sub.expires_at),
                    "renew_in_seconds": until(sub.renew_at),
                    "renewals": sub.renewals,
                    "events": sub.events,
                    "last_event_seconds_ago": ago(sub.last_event_at),
                    "failures": sub.failures,
                    "total_failures": sub.total_failures,
                    "last_error": sub.last_error,
                    "retry_in_seconds": (
                        until(sub.retry_at) if not sub.subscribed and sub.retry_at else None
                    ),
                    "unsupported": sub.unsupported,
                    "gave_up": sub.gave_up,
                    "unreliable": sub.unreliable,
                    "mismatches": sub.mismatches,
                }
            entry = {
                "udn": st.udn,
                "active": st.active,
                "holders": st.holders,
                "disabled": st.disabled,
                "unreliable_episodes": st.unreliable_episodes,
                "supports_events": self._verdicts.get(st.udn),
                "services": services,
            }
            entry["state"] = {
                "transport_state": st.transport_state,
                "track_uri": st.track_uri,
                "av_transport_uri": st.av_transport_uri,
                "track_duration": st.track_duration,
                "volume": st.volume,
                "muted": st.muted,
            }
            renderers[udn] = entry
        server = self._server
        return {
            "enabled": bool(settings.get("enabled", True)),
            "port": settings.get("port"),
            "listening": server is not None,
            "bound_ip": self._bound_ip,
            "callback_url": getattr(server, "callback_url", None) if server else None,
            "server_error": self._server_error,
            "renderers": renderers,
        }
