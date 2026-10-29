import asyncio
import os
import time
import logging
import json
from app.db import db_conn
from app.upnp import UPnPManager
from app.services.player.globals import (
    playback_monitors,
    monitor_start_times,
    monitor_starting,
    last_track_start_time,
    last_playing_seen,
    last_playing_position,
    last_stop_reason,
    record_output_plan,
    seek_generations,
    start_retries,
)
from app.services.player.state import (
    enrich_track_metadata,
    get_renderer_state_db,
    strip_art_ids,
    track_path_exists,
)
from app.services.player.queue import play_next_track_internal
from app.services.playback_plan import apply_plan_to_metadata, constraints_for_upnp
from app.services.player.history import log_history, reset_history_tracker
from app.services.audio_streaming import build_stream_url
from app.services.renderer.token_policy import staged_stream_token_ttl_seconds
from app.services.upnp.staging import StagedTrack, same_media_uri, staging

logger = logging.getLogger(__name__)

# Ignore STOPPED churn this soon after issuing Play (renderers flap during URI load).
TRANSITION_GRACE_S = 5.0
# STOPPED with the last seen position within this of the duration = track finished.
FINISH_MARGIN_S = 10.0
# STOPPED with the last seen position at or below this = the track never really
# got going (failed start), as opposed to an external stop mid-track.
FAILED_START_MAX_POS_S = 10.0
# How long to keep treating STOPPED as "still buffering" for a track that has
# not been seen PLAYING at all, before re-issuing Play.
START_RETRY_AFTER_S = 8.0
# Play re-issues per track before giving up and skipping.
MAX_START_RETRIES = 2
# Warm the next track's file this close to the end of the current one.
PREWARM_LEAD_S = 30.0
PREWARM_BYTES = 8 * 1024 * 1024
# Refresh the device volume every this many polls (~seconds), so volume
# changes made on the device itself (TV remote) reach the app slider.
VOLUME_REFRESH_POLLS = 15
# Next-track staging (SetNextAVTransportURI). Stage once the current track has
# played this far, so a flaky start is settled before the device is told
# what comes after it, while leaving it the rest of the track to buffer.
STAGE_AFTER_S = 10.0
# Don't retry staging the same queue item more often than this after a
# failure that did not disable staging (unplayable file, transient error).
STAGE_RETRY_S = 10.0
# Re-stage this long before the staged token expires (long pauses).
STAGE_REFRESH_MARGIN_S = 300.0
# A STOPPED at track end with a next track staged: wait this long for the
# renderer to roll into it before loading the next track ourselves.
STAGED_STOP_GRACE_S = 3.0
# Transport states in which a TrackURI equal to the staged URI means the
# renderer has moved on to the staged track.
STAGED_ADVANCE_STATES = ("PLAYING", "TRANSITIONING", "PAUSED_PLAYBACK")
# While AVTransport events are healthy (app/services/upnp/events.py) transport
# state and TrackURI arrive by event, so the device is only polled as a
# watchdog: GetPositionInfo this often (position is never evented; in between
# it is extrapolated) and GetTransportInfo this often, cross-checked against
# the events. Unhealthy or absent events: everything is polled every second.
EVENT_POSITION_POLL_S = 5.0
EVENT_TRANSPORT_POLL_S = 15.0


async def _sync_device_volume(upnp, udn: str) -> None:
    """Seed renderer_state.volume from the device.

    UPnP renderers never push their volume to us, so without this the app
    only knows a volume the user has already set through Jamarr — and the
    slider starts on a guess (which is how a first touch used to blast TVs).
    """
    getter = getattr(upnp, "get_volume", None)
    if getter is None:
        return
    try:
        device_volume = await getter(udn)
    except Exception:
        logger.debug(f"Volume sync failed for {udn}", exc_info=True)
        return
    if device_volume is None:
        return
    async with db_conn() as db:
        await db.execute(
            """
            UPDATE renderer_state
            SET volume = $1, updated_at = NOW()
            WHERE renderer_udn = $2 AND volume IS DISTINCT FROM $1
            """,
            int(device_volume),
            udn,
        )

# Queue index already prewarmed per renderer, and the task doing it.
_prewarmed_index: dict[str, int] = {}
_prewarm_tasks: dict[str, asyncio.Task] = {}
# When a STOPPED-at-track-end was first seen while a next track was staged.
_staged_stop_seen: dict[str, float] = {}


def _current_track_uri(upnp, udn: str) -> str | None:
    getter = getattr(upnp, "current_track_uri", None)
    if getter is None:
        return None
    try:
        return getter(udn)
    except Exception:
        logger.debug("TrackURI lookup failed for %s", udn, exc_info=True)
        return None


async def _reconcile_staged_transition(
    udn: str,
    track_uri: str | None,
    transport_state: str,
    device_position,
) -> str | None:
    """Advance the queue when the renderer has started the staged track.

    Returns "advanced" (queue moved on, nothing reloaded), "stale" (renderer
    rolled into a track that is no longer next in the queue) or None. The
    staged record is consumed here, so one transition advances exactly once.
    A record dropped while the device may still have held it (staging
    disabled, a clear refused) is matched too: the renderer can still roll
    into it, and must not leave the queue a track behind when it does.
    """
    if transport_state not in STAGED_ADVANCE_STATES:
        return None
    from_dropped = False
    staged = staging.get(udn)
    if staged is not None and same_media_uri(track_uri, staged.url):
        staging.take(udn)
    else:
        staged = staging.dropped.get(udn)
        if staged is None or not same_media_uri(track_uri, staged.url):
            return None
        staging.take_dropped(udn)
        from_dropped = True
    _staged_stop_seen.pop(udn, None)
    async with db_conn() as db:
        state = await get_renderer_state_db(db, udn)
        queue = state.get("queue") or []
        idx = state.get("current_index")
        if (
            from_dropped
            and idx is not None
            and 0 <= idx < len(queue)
            and queue[idx].get("id") == staged.track_id
        ):
            # Already the current track (we loaded it ourselves meanwhile).
            return None
        next_idx = (idx if idx is not None else -1) + 1
        if not (0 <= next_idx < len(queue)) or queue[next_idx].get("id") != staged.track_id:
            logger.warning(
                f"[Gapless] {udn} started staged track {staged.track_id}, which is no "
                f"longer next in the queue"
            )
            return "stale"
        is_playing = transport_state != "PAUSED_PLAYBACK"
        # Conditional on current_index so a skip racing this poll wins and the
        # transition can never be applied twice.
        result = await db.execute(
            """
            UPDATE renderer_state
            SET current_index = $1, position_seconds = $2, transport_state = $3,
                is_playing = $4, updated_at = NOW()
            WHERE renderer_udn = $5 AND current_index = $6
            """,
            next_idx,
            float(device_position or 0),
            transport_state,
            is_playing,
            udn,
            idx,
        )
    if not result or result.rsplit(" ", 1)[-1] == "0":
        logger.info(f"[Gapless] {udn}: queue moved during transition; not advancing")
        return None
    now = time.time()
    # Per-track bookkeeping, as play_next_track_internal does for a load.
    last_track_start_time[udn] = now
    last_playing_seen[udn] = now
    last_stop_reason.pop(udn, None)
    start_retries.pop(udn, None)
    if device_position:
        last_playing_position[udn] = float(device_position)
    else:
        last_playing_position.pop(udn, None)
    reset_history_tracker(udn)
    logger.info(
        f"[Gapless] {udn} rolled into staged track {next_idx}: "
        f"{queue[next_idx].get('title')}"
    )
    return "advanced"


async def _recover_stale_transition(upnp, udn: str) -> None:
    async with db_conn() as db:
        state = await get_renderer_state_db(db, udn)
    queue = state.get("queue") or []
    idx = state.get("current_index")
    next_idx = (idx if idx is not None else -1) + 1
    if 0 <= next_idx < len(queue):
        await play_next_track_internal(udn)
        return
    logger.info(f"[Gapless] Nothing left in the queue; stopping {udn}")
    stopper = getattr(upnp, "stop_renderer", None)
    if stopper is not None:
        await stopper(udn)
    # Our own Stop: the STOPPED that follows is neither a finished track
    # nor a failed start, so leave nothing for the monitor to misread.
    last_playing_seen.pop(udn, None)
    last_playing_position.pop(udn, None)
    async with db_conn() as db:
        await db.execute(
            """
            UPDATE renderer_state
            SET is_playing = FALSE, transport_state = 'STOPPED', updated_at = NOW()
            WHERE renderer_udn = $1
            """,
            udn,
        )


def _awaiting_staged_transition(udn: str, queue: list, idx) -> bool:
    """Hold off a STOPPED-at-end advance briefly while a next track is staged.

    Some renderers pass through STOPPED on their way into the staged URI.
    Past the grace period this counts as a miss and the caller loads the next
    track itself, exactly as without staging.
    """
    staged = staging.get(udn)
    next_idx = (idx if idx is not None else -1) + 1
    if (
        staged is None
        or not (0 <= next_idx < len(queue))
        or queue[next_idx].get("id") != staged.track_id
    ):
        _staged_stop_seen.pop(udn, None)
        return False
    first_seen = _staged_stop_seen.setdefault(udn, time.time())
    if time.time() - first_seen < STAGED_STOP_GRACE_S:
        return True
    _staged_stop_seen.pop(udn, None)
    staging.note_staged_miss(udn)
    return False


async def _sync_staged_next(
    upnp,
    udn: str,
    queue: list,
    idx,
    device_position,
    track_uri: str | None,
) -> None:
    """Make the renderer's staged next track match queue[idx + 1].

    Runs every PLAYING poll, so queue edits (reorder, delete, append, a new
    queue) re-stage or clear within a poll without each mutation path having
    to know about staging.
    """
    allowed = getattr(upnp, "next_track_staging_allowed", None)
    if allowed is None or not hasattr(upnp, "set_next_track"):
        return
    # A record dropped since the last poll (new load, unplayable next, fault)
    # may still be on the device: clear it first, even if staging was just
    # switched off, or the renderer rolls into a track the queue moved past.
    if udn in staging.needs_clear:
        await _clear_staged_next(upnp, udn)
    if not allowed(udn):
        return
    # Without a TrackURI the transition could not be recognised, and the
    # queue would silently fall a track behind the renderer.
    if not track_uri:
        return
    staged = staging.get(udn)
    if staged and same_media_uri(track_uri, staged.url):
        return  # transition in flight; the next poll reconciles it
    started_at = last_track_start_time.get(udn, 0)
    if last_playing_seen.get(udn, 0) < started_at:
        return
    if (device_position or 0) < STAGE_AFTER_S:
        return

    next_idx = (idx if idx is not None else -1) + 1
    if not (0 <= next_idx < len(queue)):
        if staged:
            await _clear_staged_next(upnp, udn)
        return
    target = queue[next_idx]
    target_id = target.get("id")
    if target_id is None:
        return
    now = time.time()
    if (
        staged
        and staged.track_id == target_id
        and (staged.expires_at is None or now < staged.expires_at - STAGE_REFRESH_MARGIN_S)
    ):
        return
    attempt = staging.last_attempt.get(udn)
    if attempt and attempt[0] == target_id and now - attempt[1] < STAGE_RETRY_S:
        return
    staging.last_attempt[udn] = (target_id, now)

    current_duration = 0
    if idx is not None and 0 <= idx < len(queue):
        current_duration = queue[idx].get("duration_seconds") or 0
    lead_s = max(0.0, float(current_duration) - float(device_position or 0))
    base_url = getattr(upnp, "renderer_base_url", None) or upnp.base_url
    async with db_conn() as db:
        enriched = await enrich_track_metadata(target, db)
        if not track_path_exists(enriched):
            logger.info(f"[Gapless] Next track {target_id} is not on disk; not staging it")
            if staged:
                staging.forget(udn)
                await _clear_staged_next(upnp, udn)
            return
        ttl = staged_stream_token_ttl_seconds(lead_s, enriched.get("duration_seconds"))
        stream = await build_stream_url(
            db,
            track_id=int(target_id),
            base_url=base_url,
            user_id=enriched.get("user_id"),
            duration_seconds=enriched.get("duration_seconds"),
            renderer_kind="upnp",
            queue=queue,
            queue_index=next_idx,
            ttl_seconds=ttl,
            # Staged exactly as a loaded track would be planned.
            constraints=constraints_for_upnp(
                (getattr(upnp, "renderers", None) or {}).get(udn), udn
            ),
        )
    metadata = dict(enriched)
    metadata["stream_url"] = stream.url
    if stream.mime_type:
        metadata["mime"] = stream.mime_type
    apply_plan_to_metadata(metadata, stream.plan)
    if stream.plan is not None:
        record_output_plan(udn, int(target_id), stream.plan.as_dict())
    try:
        staged_url = await upnp.set_next_track(udn, int(target_id), metadata)
    except Exception as exc:
        # The device may still hold the old staged URI: stop tracking it as
        # staged, but clear it (best effort) and keep recognising it.
        if staged:
            staging.forget(udn)
        if not isinstance(exc, ValueError):  # ValueError: not registered now
            staging.note_failure(udn, exc)
        if udn in staging.needs_clear:
            await _clear_staged_next(upnp, udn)
        return
    staging.record(
        udn,
        StagedTrack(
            queue_index=next_idx,
            track_id=target_id,
            url=staged_url or stream.url,
            staged_at=now,
            expires_at=now + ttl,
        ),
    )


async def _clear_staged_next(upnp, udn: str) -> None:
    """Best-effort empty SetNextAVTransportURI; never raises."""
    clear = getattr(upnp, "clear_next_track", None)
    if clear is None:
        staging.needs_clear.discard(udn)
        return
    try:
        await clear(udn)
    except Exception:
        logger.debug("Clearing the staged next track failed for %s", udn, exc_info=True)
        staging.cleared(udn, ok=False)


async def _prewarm_next_track(path: str) -> None:
    """Read the head of the file to pull it into the OS page cache.

    Cold NFS reads are slow enough that some renderers (Server room TV) give
    up starting a track; serving the first fetch from RAM removes that stall.
    """
    try:
        import aiofiles

        from app.config import get_music_path

        if not os.path.isabs(path):
            path = os.path.join(get_music_path(), path)
        async with aiofiles.open(path, "rb") as fh:
            remaining = PREWARM_BYTES
            while remaining > 0:
                chunk = await fh.read(min(512 * 1024, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
        logger.info(f"[Player] Prewarmed next track: {os.path.basename(path)}")
    except Exception:
        logger.debug("Prewarm failed for %s", path, exc_info=True)


class _DeviceReader:
    """Reads position, transport state and TrackURI once per monitor loop.

    Without healthy events: GetPositionInfo + GetTransportInfo every loop, as
    always. With them: the event-derived state, plus a watchdog poll every
    EVENT_POSITION_POLL_S (and transport every EVENT_TRANSPORT_POLL_S) whose
    results win and are reported back so missed events are noticed. An
    AVTransport event (state or TrackURI change) wakes the loop at once.

    A seek (``player.globals.note_seek``) invalidates the polled baseline:
    the next read polls position again rather than extrapolating a pre-seek
    one, so progress, near-end staging and history see where playback is.
    """

    def __init__(self, upnp, udn: str) -> None:
        self.upnp = upnp
        self.udn = udn
        self.events = getattr(upnp, "events", None)
        self.event_mode = False
        self.generation = -1
        self.position = None
        self.position_at = 0.0
        self.transport_at = 0.0
        self.seek_generation = seek_generations.get(udn, 0)

    def rc_healthy(self) -> bool:
        return bool(self.events is not None and self.events.rc_healthy(self.udn))

    def seeked(self) -> bool:
        """A seek happened since the last position poll."""
        return seek_generations.get(self.udn, 0) != self.seek_generation

    async def _poll_position(self):
        # Taken before the call: a seek landing during the poll forces another.
        self.seek_generation = seek_generations.get(self.udn, 0)
        rel_time, _ = await self.upnp.get_position(self.udn)
        self.position = rel_time
        self.position_at = time.monotonic()
        return rel_time

    async def read(self):
        events = self.events
        snap = None
        if events is not None:
            events.check(self.udn)
            snap = events.snapshot(self.udn)
        if snap is None or not snap.avt_healthy or not snap.transport_state:
            if self.event_mode:
                logger.info(f"[Player] Monitor {self.udn}: events unhealthy, polling every second")
            self.event_mode = False
            rel_time = await self._poll_position()
            transport_state = await self.upnp.get_transport_info(self.udn)
            return rel_time, transport_state, _current_track_uri(self.upnp, self.udn)

        if not self.event_mode:
            logger.info(f"[Player] Monitor {self.udn}: events healthy, polling as watchdog only")
            self.event_mode = True
        now = time.monotonic()
        changed = snap.generation != self.generation
        self.generation = snap.generation
        transport_state = snap.transport_state
        track_uri = snap.track_uri
        if (
            changed
            or self.position is None
            or self.seeked()
            or now - self.position_at >= EVENT_POSITION_POLL_S
        ):
            rel_time = await self._poll_position()
            polled_uri = _current_track_uri(self.upnp, self.udn)
            polled_state = None
            if now - self.transport_at >= EVENT_TRANSPORT_POLL_S:
                self.transport_at = now
                polled_state = await self.upnp.get_transport_info(self.udn)
            events.note_poll(self.udn, transport_state=polled_state, track_uri=polled_uri)
            # Polls are the freshest truth; note_poll folded them into events.
            transport_state = polled_state or transport_state
            track_uri = polled_uri or track_uri
            self.generation = events.snapshot(self.udn).generation
            return rel_time, transport_state, track_uri

        # Between watchdog polls: extrapolate from the last polled position.
        rel_time = self.position or 0
        if transport_state == "PLAYING":
            rel_time = rel_time + int(now - self.position_at)
            if snap.track_duration:
                rel_time = min(rel_time, int(snap.track_duration))
        return rel_time, transport_state, track_uri

    async def idle(self, seconds: float) -> None:
        if self.event_mode and self.events is not None:
            await self.events.wait_for_change(self.udn, self.generation, seconds)
        else:
            await asyncio.sleep(seconds)


def _mark_monitor_starting(udn: str):
    monitor_starting[udn] = time.time()


def _clear_monitor_starting(udn: str):
    monitor_starting.pop(udn, None)


def _is_monitor_starting(udn: str, window_s: float = 10.0) -> bool:
    started_at = monitor_starting.get(udn)
    return bool(started_at) and (time.time() - started_at) < window_s


def start_monitor_task(udn: str):
    existing = playback_monitors.get(udn)
    if existing and not existing.done():
        return existing
    playback_monitors[udn] = asyncio.create_task(monitor_upnp_playback(udn))
    monitor_start_times[udn] = time.time()
    return playback_monitors[udn]


async def monitor_upnp_playback(udn: str):
    """Background task to follow a UPnP device (events + polling) and update DB."""
    logger.info(f"[Player] Starting UPnP monitor for {udn}")
    upnp = UPnPManager.get_instance()
    # Subscribe to the renderer's events while the monitor runs; released
    # (with a linger, so pause/skip does not churn subscriptions) on exit.
    events = getattr(upnp, "events", None)
    if events is not None:
        events.acquire(udn)
    try:
        await _monitor_loop(udn, upnp)
    finally:
        if events is not None:
            events.release(udn)


async def _monitor_loop(udn: str, upnp):
    reader = _DeviceReader(upnp, udn)

    # Grace period: Wait for device to react to Play command before polling
    logger.info(f"[Player] Monitor {udn}: Task started, waiting 3s grace period...")
    await asyncio.sleep(3)

    # Let the UI slider reflect the device's real volume from the start.
    await _sync_device_volume(upnp, udn)

    was_playing = False  # Initialize to prevent UnboundLocalError
    consecutive_errors = 0
    error_started_at = 0.0  # when the first error in the current streak occurred
    poll_count = 0
    try:
        while True:
            poll_count += 1
            # Evented volume is written as it arrives (events.py); poll it
            # only when RenderingControl events are not healthy.
            if poll_count % VOLUME_REFRESH_POLLS == 0 and not reader.rc_healthy():
                await _sync_device_volume(upnp, udn)
            # 1. Fetch position & transport from UPnP
            try:
                logger.info(f"[Player] Monitor {udn}: Polling...")
                rel_time, transport_state, track_uri = await reader.read()
                logger.info(f"[Player] Monitor {udn}: Got pos={rel_time}, state={transport_state}")
                consecutive_errors = 0  # Reset on success
                error_started_at = 0.0
            except Exception as e:
                now = time.time()
                consecutive_errors += 1
                if error_started_at == 0.0:
                    error_started_at = now
                error_duration = now - error_started_at
                # Kill only after 5 minutes of continuous errors
                if error_duration > 300:
                    logger.error(
                        f"[Player] Monitor {udn}: Errors persisted {error_duration:.0f}s, stopping"
                    )
                    break
                # Exponential backoff: 1s → 2s → 4s → 8s → 16s → cap 30s
                backoff = min(1 << (consecutive_errors - 1), 30)
                logger.error(
                    f"[Player] Monitor {udn}: Error fetching state (#{consecutive_errors}, "
                    f"backoff {backoff}s, streak {error_duration:.0f}s): {e}"
                )
                await asyncio.sleep(backoff)
                continue

            # 1b. Gapless: has the renderer rolled into the staged next track?
            # That never shows up as STOPPED, so it is matched on TrackURI.
            transition = await _reconcile_staged_transition(
                udn, track_uri, transport_state, rel_time
            )
            if transition == "stale":
                # The queue changed after staging and the renderer already
                # started the old next track: load the right one (or stop at
                # the end of the queue) rather than let it play on.
                try:
                    await _recover_stale_transition(upnp, udn)
                except Exception:
                    logger.exception(f"[Gapless] Recovering stale transition failed for {udn}")
                await asyncio.sleep(4)
                continue

            # 2. Update DB
            finished_reason = None
            replay_track = None
            stage_context = None
            async with db_conn() as db:
                # What the DB currently thinks (may differ from the device)
                state = await get_renderer_state_db(db, udn)
                was_playing = state["is_playing"]

                # Raw device-reported position, before the keep-moving hack below.
                device_position = rel_time

                if transport_state == "PLAYING":
                    last_playing_seen[udn] = time.time()
                    _staged_stop_seen.pop(udn, None)
                    # Playing again, however that came about: the last halt is
                    # history and must not keep explaining itself to the UI.
                    last_stop_reason.pop(udn, None)
                    if device_position:
                        last_playing_position[udn] = float(device_position)
                        if device_position > FAILED_START_MAX_POS_S:
                            # The track is definitely going; the start-retry
                            # budget belongs to the next troubled start.
                            start_retries.pop(udn, None)

                # Update live stats from the device
                if transport_state == "PLAYING" and (rel_time is None or rel_time == 0):
                    # Some renderers report 0 at start; keep moving forward based on last known position.
                    rel_time = max(0, state.get("position_seconds", 0) + 1)
                state["position_seconds"] = rel_time
                state["transport_state"] = transport_state
                state["is_playing"] = transport_state not in [
                    "PAUSED_PLAYBACK",
                    "STOPPED",
                    "NO_MEDIA_PRESENT",
                ]

                # Auto-advance logic:
                # Treat STOPPED as end-of-track only when the evidence says so.
                # The device's last seen position vs the track duration tells us
                # *where* playback stopped, which distinguishes "finished" from
                # "failed to start" (retry) from "externally stopped" (halt).
                # recently_playing covers renderers that signal end-of-track as
                # PLAYING -> PAUSED_PLAYBACK -> STOPPED: the PAUSED poll clears
                # is_playing in the DB, so was_playing alone would miss it.
                if transport_state in ["STOPPED", "NO_MEDIA_PRESENT"]:
                    recently_playing = was_playing or (
                        time.time() - last_playing_seen.get(udn, 0) <= 5.0
                    )
                    if recently_playing:
                        started_at = last_track_start_time.get(udn, 0)
                        time_since_start = time.time() - started_at
                        # Whether the device has reached PLAYING for *this* track;
                        # was_playing is set optimistically at Play time and
                        # last_playing_seen/-position may be from the previous
                        # track, so everything is gated on started_at.
                        played_since_start = last_playing_seen.get(udn, 0) >= started_at
                        last_pos = (
                            last_playing_position.get(udn, 0.0) if played_since_start else 0.0
                        )
                        duration = 0
                        queue = state.get("queue") or []
                        idx = state.get("current_index")
                        if idx is not None and 0 <= idx < len(queue):
                            duration = queue[idx].get("duration_seconds") or 0
                        retries = start_retries.get(udn, 0)
                        # min-clamp so very short tracks aren't "finished" at 0s
                        finish_threshold = max(duration - FINISH_MARGIN_S, duration * 0.5)

                        if time_since_start < TRANSITION_GRACE_S:
                            logger.info(
                                f"[Player] Ignoring STOPPED state during transition (started {time_since_start:.1f}s ago)"
                            )
                        elif duration > 0 and played_since_start and last_pos >= finish_threshold:
                            if _awaiting_staged_transition(udn, queue, idx):
                                logger.info(
                                    "[Gapless] STOPPED at track end with a next track "
                                    "staged; waiting for the renderer to start it"
                                )
                            else:
                                logger.info(
                                    f"[Player] Track finished detection: stopped at "
                                    f"{last_pos:.0f}s of {duration:.0f}s"
                                )
                                # Trigger next track outside DB loop; helper opens its own connection.
                                finished_reason = "stopped"
                        elif duration > 0 and (
                            not played_since_start or last_pos <= FAILED_START_MAX_POS_S
                        ):
                            # Failed start: never reached PLAYING, or died within
                            # the first seconds (Server room TV does both).
                            if not played_since_start and time_since_start < START_RETRY_AFTER_S:
                                logger.info(
                                    f"[Player] Ignoring STOPPED: renderer has not started the track "
                                    f"yet ({time_since_start:.1f}s since Play)"
                                )
                            elif retries < MAX_START_RETRIES:
                                start_retries[udn] = retries + 1
                                # Re-issue Play outside the DB loop.
                                replay_track = queue[idx]
                            else:
                                logger.warning(
                                    f"[Player] Track failed to start after {MAX_START_RETRIES} "
                                    f"Play retries; skipping to next"
                                )
                                finished_reason = "stopped"
                        elif duration > 0:
                            # Stopped mid-track: either an external stop (TV
                            # remote, another controller) or the renderer
                            # dropping out. We cannot tell the two apart, so
                            # halt rather than fight it -- but keep the position
                            # so Resume carries on from here, and record why we
                            # stopped so the UI can say so instead of just
                            # falling silent.
                            logger.warning(
                                f"[Player] Playback stopped mid-track at {last_pos:.0f}s of "
                                f"{duration:.0f}s; stopping queue"
                            )
                            # The device reports 0 once stopped; persisting that
                            # would throw away the listener's place in the track.
                            state["position_seconds"] = last_pos
                            last_stop_reason[udn] = {
                                "reason": "renderer_stopped",
                                "position_seconds": last_pos,
                                "at": time.time(),
                            }
                            await db.execute(
                                """
                                UPDATE renderer_state
                                SET position_seconds = $1, transport_state = $2, is_playing = $3, updated_at = NOW()
                                WHERE renderer_udn = $4
                                """,
                                state["position_seconds"],
                                state["transport_state"],
                                bool(state["is_playing"]),
                                udn,
                            )
                        else:
                            # No duration metadata; fall back to time-based logic.
                            if not played_since_start and time_since_start < 30.0:
                                logger.info(
                                    f"[Player] Ignoring STOPPED: renderer has not started the track "
                                    f"yet ({time_since_start:.1f}s since Play)"
                                )
                            else:
                                if not played_since_start:
                                    logger.warning(
                                        f"[Player] Renderer never started the track after "
                                        f"{time_since_start:.0f}s; skipping to next"
                                    )
                                logger.info(
                                    f"[Player] Track finished detection: State={transport_state}, Expected=Playing"
                                )
                                finished_reason = "stopped"
                    else:
                        # Genuinely idle; just persist snapshot of state.
                        await db.execute(
                            """
                            UPDATE renderer_state
                            SET position_seconds = $1, transport_state = $2, is_playing = $3, updated_at = NOW()
                            WHERE renderer_udn = $4
                            """,
                            state["position_seconds"],
                            state["transport_state"],
                            bool(state["is_playing"]),
                            udn,
                        )
                else:
                    # Still playing or paused/buffering. If user paused via remote, sync is_playing to False.
                    if "PAUSE" in transport_state:
                        state["is_playing"] = False

                    # Race Condition Fix: status-only UPDATE so we do not overwrite queue/volume changes
                    # that might have happened via API while this UPnP poll was in flight.
                    await db.execute(
                        """
                        UPDATE renderer_state
                        SET position_seconds = $1, transport_state = $2, is_playing = $3, updated_at = NOW()
                        WHERE renderer_udn = $4
                        """,
                        state["position_seconds"],
                        state["transport_state"],
                        bool(state["is_playing"]),
                        udn,
                    )

                    # Staging runs after this block, off the DB connection.
                    if transport_state == "PLAYING":
                        stage_context = (
                            list(state.get("queue") or []),
                            state.get("current_index"),
                        )

                    # Watchdog: some renderers get stuck reporting PLAYING at position 0
                    # after the audio actually ended, never emitting STOPPED. If the device
                    # has reported no real position for longer than the track's duration
                    # plus a margin, assume the track finished.
                    if was_playing and transport_state == "PLAYING":
                        started = last_track_start_time.get(udn)
                        duration = 0
                        queue = state.get("queue") or []
                        idx = state.get("current_index")
                        if idx is not None and 0 <= idx < len(queue):
                            duration = queue[idx].get("duration_seconds") or 0
                        if (
                            started
                            and duration > 0
                            and (device_position or 0) <= 1
                            and time.time() - started > duration + 60
                        ):
                            logger.warning(
                                f"[Player] Watchdog: renderer stuck PLAYING at position 0 for "
                                f"{time.time() - started:.0f}s (track is {duration:.0f}s); assuming finished"
                            )
                            finished_reason = "watchdog"

                        # Prewarm: pull the next track's file head into the page
                        # cache shortly before the transition, so the renderer's
                        # first fetch is served from RAM instead of cold NFS.
                        next_idx = (idx if idx is not None else -1) + 1
                        if (
                            duration > 0
                            and device_position
                            and device_position >= duration - PREWARM_LEAD_S
                            and 0 <= next_idx < len(queue)
                            and _prewarmed_index.get(udn) != next_idx
                        ):
                            next_path = queue[next_idx].get("path")
                            if next_path:
                                _prewarmed_index[udn] = next_idx
                                _prewarm_tasks[udn] = asyncio.create_task(
                                    _prewarm_next_track(next_path)
                                )

                # History logging for remote playback (based on renderer state queue)
                if (
                    state["is_playing"]
                    and state["current_index"] is not None
                    and state["current_index"] >= 0
                ):
                    queue = state.get("queue") or []
                    if 0 <= state["current_index"] < len(queue):
                        track = queue[state["current_index"]]
                        
                        # Only check if not already logged
                        if not track.get("logged", False):
                            track_id = track.get("id")
                            duration = track.get("duration_seconds") or 0
                            
                            # Threshold check
                            threshold = min(30, duration * 0.2) if duration > 0 else 30
                            
                            if rel_time >= threshold:
                                renderer_ip = (
                                    upnp.renderers.get(udn, {}).get("ip")
                                    if upnp.renderers
                                    else None
                                )
                                await log_history(
                                    db,
                                    track_id,
                                    client_ip=renderer_ip or "unknown",
                                    client_id=udn,
                                    user_id=track.get("user_id"),
                                )
                                
                                # Mark logged and persist
                                track["logged"] = True
                                await db.execute(
                                    "UPDATE renderer_state SET queue = $1 WHERE renderer_udn = $2",
                                    json.dumps(strip_art_ids(queue)),
                                    udn,
                                )

            # Execute side effects outside DB context (avoids holding a transaction open)
            if replay_track is not None:
                logger.warning(
                    f"[Player] Track failed to start ('{replay_track.get('title')}'); "
                    f"re-issuing Play (attempt {start_retries.get(udn, 0)}/{MAX_START_RETRIES})"
                )
                try:
                    await upnp.play_track(replay_track["id"], replay_track["path"], replay_track)
                    last_track_start_time[udn] = time.time()
                    last_playing_position.pop(udn, None)
                except Exception:
                    logger.exception(f"[Player] Play retry failed for {udn}")
                await asyncio.sleep(4)  # Give the retried track a moment to start
            elif finished_reason:
                # A single bad track must not take the monitor down with it --
                # the loop is what drives auto-advance for this renderer.
                try:
                    await play_next_track_internal(udn)
                except Exception:
                    logger.exception(f"[Player] Auto-advance failed for {udn}")
                await asyncio.sleep(4)  # Give the new track a moment to start
            elif stage_context is not None:
                try:
                    await _sync_staged_next(
                        upnp, udn, *stage_context, device_position, track_uri
                    )
                except Exception:
                    logger.exception(f"[Gapless] Staging the next track failed for {udn}")

            # 1 s, or sooner when an AVTransport event arrives.
            await reader.idle(1)

    except asyncio.CancelledError:
        logger.info(f"UPnP monitor for {udn} cancelled")
    except Exception as e:
        logger.error(f"UPnP monitor error for {udn}: {e}")
        import traceback

        traceback.print_exc()
