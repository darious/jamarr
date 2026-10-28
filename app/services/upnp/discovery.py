"""Server-side UPnP renderer discovery.

Three inputs feed one per-description-URL record table:

* **searches** — bounded M-SEARCH bursts for MediaRenderer devices *and*
  AVTransport services (some renderers only answer the service target), sent
  a few times ~500 ms apart because multicast is lossy;
* **a persistent SSDP listener** — ``ssdp:alive`` / ``ssdp:update`` /
  ``ssdp:byebye`` advertisements, so arrivals and departures are seen between
  searches (falls back to polling search if the socket cannot bind);
* **manual add / subnet sweep** — unicast M-SEARCH to one host, then a few
  guessed description URLs.

Liveness is separate from hydration. Hydrating a description (fetch XML and
SCPDs, build DmrDevices, query protocols, pick an icon, save to the DB) only
happens for a new LOCATION, a changed BOOTID/CONFIGID, an explicit refresh or
after the device was found unreachable. Every other sighting just bumps
``last_seen``. A device is only marked unavailable after a byebye or after its
advertised lifetime plus a grace period has passed, *and* a bounded HTTP probe
of its description fails — one lost multicast reply never removes it. Saved
metadata and settings are kept either way.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
import time
from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, Iterable, Optional
from urllib.parse import urlparse

import aiohttp
from async_upnp_client.advertisement import SsdpAdvertisementListener
from async_upnp_client.search import SsdpSearchListener

from app.db import db_conn
from app.services.upnp.network import interface_name, scan_network
from app.services.upnp.tree import (
    avtransport_service,
    make_dmr,
    playable_endpoints,
    rendering_control_service,
)
from app.services.upnp.utils import _pick_best_icon

logger = logging.getLogger(__name__)

SSDP_TARGET_MEDIA_RENDERER = "urn:schemas-upnp-org:device:MediaRenderer:1"
SSDP_TARGET_AVTRANSPORT = "urn:schemas-upnp-org:service:AVTransport:1"
SEARCH_TARGETS = (SSDP_TARGET_MEDIA_RENDERER, SSDP_TARGET_AVTRANSPORT)

# One scan = this many transmissions of every search target, this far apart.
SEARCH_TRANSMISSIONS = 3
SEARCH_INTERVAL_SECONDS = 0.5
SEARCH_MX = 2

# Background search cadence. With the advertisement listener running, alive /
# byebye do most of the work and searches are a safety net.
POLL_INTERVAL_SECONDS = 30
POLL_INTERVAL_WITH_LISTENER_SECONDS = 60

# Liveness. UDA's CACHE-CONTROL max-age (default when absent), then a grace
# period, then a probe. A byebye probes after a short delay so a quick
# byebye/alive restart pair does not flap availability.
DEFAULT_MAX_AGE_SECONDS = 1800
LIVENESS_GRACE_SECONDS = 120
BYEBYE_PROBE_DELAY_SECONDS = 3.0
PROBE_TIMEOUT_SECONDS = 3.0

# Hydration: at most this many descriptions at once, each with a deadline,
# so one slow device cannot stall the rest.
HYDRATE_CONCURRENCY = 4
HYDRATE_DEADLINE_SECONDS = 20.0

# Manual add / subnet sweep.
MANUAL_UNICAST_TIMEOUT_SECONDS = 2.0
SUBNET_UNICAST_TIMEOUT_SECONDS = 1.5
SUBNET_HTTP_TIMEOUT_SECONDS = 1.5
MANUAL_HTTP_TIMEOUT_SECONDS = 3.0
SUBNET_CONCURRENCY = 32
GUESSED_DESCRIPTION_URLS = (
    "http://{host}:49152/description.xml",
    "http://{host}:8080/description.xml",
    "http://{host}:1400/xml/device_description.xml",
    "http://{host}:60053/upnp/dev/uuid/description.xml",
)

# Cooldown steps for persistently unreachable renderers (seconds).
_FAILURE_COOLDOWN_STEPS = [120, 300, 900, 3600]

# After this many consecutive failures the renderer is suspended: probed at
# most every _SUSPENDED_RETRY_INTERVAL, or immediately if it re-announces with
# a new BOOTID (i.e. its UPnP stack actually restarted).
_SUSPEND_AFTER_FAILURES = 5
_SUSPENDED_RETRY_INTERVAL = 6 * 3600

_MAX_AGE_RE = re.compile(r"max-age\s*=\s*(\d+)", re.IGNORECASE)


def is_renderer_target(st: Optional[str]) -> bool:
    """Whether an ST/NT names something we can play to."""
    return bool(st) and ("MediaRenderer" in st or "AVTransport" in st)


def _hdr(headers: Any, key: str) -> Optional[str]:
    """Case-insensitive header lookup for CaseInsensitiveDict or plain dicts."""
    getter = getattr(headers, "get_lower", None)
    if getter is not None:
        value = getter(key.lower())
        if value is not None:
            return value
    for candidate in (key, key.upper(), key.lower()):
        try:
            value = headers.get(candidate)
        except Exception:
            value = None
        if value is not None:
            return value
    return None


def _udn_from_headers(headers: Any) -> Optional[str]:
    udn = _hdr(headers, "_udn")
    if udn:
        return udn
    usn = _hdr(headers, "usn") or ""
    if usn.startswith("uuid:"):
        return usn.split("::", 1)[0]
    return None


def _max_age(headers: Any) -> Optional[int]:
    match = _MAX_AGE_RE.search(_hdr(headers, "cache-control") or "")
    return int(match.group(1)) if match else None


@dataclass
class Sighting:
    """One device seen via search reply, advertisement or manual probe."""

    location: str
    udns: set[str] = field(default_factory=set)
    is_renderer: bool = False
    bootid: Optional[str] = None
    configid: Optional[str] = None
    max_age: Optional[int] = None
    source: str = "search"

    @classmethod
    def from_headers(cls, headers: Any, source: str) -> Optional["Sighting"]:
        location = _hdr(headers, "location")
        if not location:
            return None
        st = _hdr(headers, "st") or _hdr(headers, "nt")
        udn = _udn_from_headers(headers)
        return cls(
            location=location,
            udns={udn} if udn else set(),
            is_renderer=is_renderer_target(st),
            bootid=_hdr(headers, "bootid.upnp.org"),
            configid=_hdr(headers, "configid.upnp.org"),
            max_age=_max_age(headers),
            source=source,
        )

    def merge(self, other: "Sighting") -> None:
        self.udns |= other.udns
        self.is_renderer = self.is_renderer or other.is_renderer
        self.bootid = other.bootid or self.bootid
        self.configid = other.configid or self.configid
        self.max_age = other.max_age or self.max_age


@dataclass
class LocationRecord:
    """Discovery state for one description URL (one device tree)."""

    location: str
    udns: list[str] = field(default_factory=list)  # registered playable endpoints
    ssdp_udns: set[str] = field(default_factory=set)  # UDNs seen advertising it
    bootid: Optional[str] = None
    configid: Optional[str] = None
    max_age: int = DEFAULT_MAX_AGE_SECONDS
    last_seen: float = 0.0  # monotonic
    last_seen_wall: float = 0.0
    available: bool = False
    hydrated: bool = False
    is_renderer: bool = True
    stale: bool = False  # re-hydrate on next sighting
    byebye: bool = False


class UPnPDiscovery:
    def __init__(self, manager):
        self.manager = manager
        self._running = False
        self._discovery_task: Optional[asyncio.Task] = None
        self.is_scanning_subnet = False
        self.scan_msg = ""
        self.scan_progress = 0
        self.scan_total_hosts = 0
        self._subnet_task: Optional[asyncio.Task] = None
        # location -> {"failures": int, "cooldown_until": float,
        #              "bootid": Optional[str], "suspended": bool}
        self._failure_state: Dict[str, dict] = {}

        self._locations: Dict[str, LocationRecord] = {}
        self._udn_location: Dict[str, str] = {}
        self._inflight: Dict[str, asyncio.Future] = {}
        self._probe_tasks: Dict[str, asyncio.Task] = {}
        self._hydrate_sem = asyncio.Semaphore(HYDRATE_CONCURRENCY)
        self._scan_lock = asyncio.Lock()
        self._listener: Any = None
        self._listener_status = "stopped"
        self.hydration_count = 0

        # Seams for tests (and nothing else): the SSDP layer, the HTTP probe,
        # the availability write-through and the monotonic clock.
        self._search_impl: Callable[..., Awaitable[None]] = self._ssdp_search
        self._listener_factory: Callable[..., Any] = SsdpAdvertisementListener
        self._probe_impl: Callable[[str, float], Awaitable[bool]] = self._http_probe
        self._clock: Callable[[], float] = time.monotonic

        self._last_scan: dict[str, Any] = {}
        self._descriptor_failures: deque = deque(maxlen=20)
        self._transitions: deque = deque(maxlen=50)

    # ------------------------------------------------------------------ loop

    def start_background_scan(self):
        """Start background discovery loop."""
        if not self._running:
            self._running = True
            self._discovery_task = asyncio.create_task(self._discovery_loop())
            self.manager.log("Started background UPnP discovery")

    async def stop_background_scan(self):
        """Stop background discovery loop."""
        self._running = False
        if self._discovery_task:
            self._discovery_task.cancel()
            try:
                await asyncio.wait_for(self._discovery_task, timeout=2.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
        await self._stop_listener()
        self.cancel_subnet_scan()
        for task in list(self._probe_tasks.values()):
            task.cancel()
        self.manager.log("Stopped background UPnP discovery")

    async def _discovery_loop(self):
        """Periodic discovery loop to find and maintain renderer list."""
        try:
            await self.load_persisted_renderers()
        except Exception as e:
            logger.error(f"Loading persisted renderers failed: {e}")
        await self._start_listener()

        while self._running:
            try:
                if self._refresh_local_ip():
                    await self._stop_listener()
                    await self._start_listener()
                await self.discover(timeout=3)
                interval = (
                    POLL_INTERVAL_WITH_LISTENER_SECONDS
                    if self._listener is not None
                    else POLL_INTERVAL_SECONDS
                )
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Discovery loop error: {e}")
                await asyncio.sleep(POLL_INTERVAL_SECONDS)

    def _refresh_local_ip(self) -> bool:
        refresh = getattr(self.manager, "refresh_local_ip", None)
        if refresh is None:
            return False
        try:
            return bool(refresh())
        except Exception:
            return False

    def _source_addr(self) -> Optional[tuple[str, int]]:
        source_ip = getattr(self.manager, "source_ip", None)
        return (source_ip, 0) if source_ip else None

    # -------------------------------------------------------------- listener

    async def _start_listener(self) -> None:
        if self._listener is not None:
            return
        try:
            listener = self._listener_factory(
                async_on_alive=self._on_advertisement,
                async_on_update=self._on_advertisement,
                async_on_byebye=self._on_byebye,
                source=self._source_addr(),
            )
            await listener.async_start()
        except Exception as e:
            self._listener = None
            self._listener_status = f"unavailable ({e}); polling search only"
            logger.warning(
                "SSDP advertisement listener could not start (%s); "
                "falling back to polling search every %ss",
                e,
                POLL_INTERVAL_SECONDS,
            )
            return
        self._listener = listener
        self._listener_status = "running"
        self.manager.log("SSDP advertisement listener started")

    async def _stop_listener(self) -> None:
        listener, self._listener = self._listener, None
        if listener is None:
            return
        self._listener_status = "stopped"
        try:
            await listener.async_stop()
        except Exception as e:
            logger.debug(f"Error stopping SSDP listener: {e}")

    async def _on_advertisement(self, headers: Any) -> None:
        """ssdp:alive / ssdp:update."""
        try:
            sighting = Sighting.from_headers(headers, source="advertisement")
            if sighting is None:
                return
            await self._handle_sighting(sighting)
        except Exception as e:
            logger.debug(f"Error handling SSDP advertisement: {e}")

    async def _on_byebye(self, headers: Any) -> None:
        try:
            udn = _udn_from_headers(headers)
            location = self._udn_location.get(udn) if udn else None
            if location is None:
                location = _hdr(headers, "location")
            record = self._locations.get(location) if location else None
            if record is None or not record.available:
                return
            record.byebye = True
            self.manager.log(f"ssdp:byebye from {udn or location}")
            self._schedule_probe(record.location, delay=BYEBYE_PROBE_DELAY_SECONDS)
        except Exception as e:
            logger.debug(f"Error handling SSDP byebye: {e}")

    # ---------------------------------------------------------------- search

    async def _ssdp_search(
        self,
        targets: Iterable[str],
        timeout: float,
        on_headers: Callable[[Any], None],
        target_addr: Optional[tuple[str, int]] = None,
        transmissions: int = SEARCH_TRANSMISSIONS,
    ) -> None:
        """Send ``transmissions`` bursts of every target, then wait for replies."""
        listener = SsdpSearchListener(
            callback=on_headers,
            source=self._source_addr(),
            target=target_addr,
            timeout=SEARCH_MX,
        )
        await listener.async_start()
        try:
            for i in range(transmissions):
                for st in targets:
                    listener.search_target = st
                    listener.async_search()
                if i < transmissions - 1:
                    await asyncio.sleep(SEARCH_INTERVAL_SECONDS)
            remaining = timeout - (transmissions - 1) * SEARCH_INTERVAL_SECONDS
            await asyncio.sleep(max(remaining, 0.5))
        finally:
            listener.async_stop()

    async def discover(self, timeout=5, refresh: bool = False) -> list[dict]:
        """Search for renderers and hydrate anything new or changed.

        Overlapping calls do not start a second burst: they wait for the
        scan in flight and return its result.
        """
        if self._scan_lock.locked():
            async with self._scan_lock:
                pass
            return self.available_renderers()

        async with self._scan_lock:
            await self.manager._ensure_session()
            started = self._clock()
            self.manager.log(f"Starting UPnP discovery (timeout={timeout}s)...")
            replies: Counter = Counter()
            sightings: Dict[str, Sighting] = {}

            def on_headers(headers: Any) -> None:
                sighting = Sighting.from_headers(headers, source="search")
                if sighting is None:
                    return
                replies[_hdr(headers, "st") or "?"] += 1
                existing = sightings.get(sighting.location)
                if existing is None:
                    sightings[sighting.location] = sighting
                else:
                    existing.merge(sighting)

            error = None
            try:
                await self._search_impl(SEARCH_TARGETS, timeout, on_headers)
            except Exception as e:
                error = str(e)
                logger.error(f"Discovery error: {e}")
                self.manager.log(f"Discovery error: {e}")

            outcomes = Counter()
            results = await asyncio.gather(
                *(
                    self._handle_sighting(s, refresh=refresh, outcomes=outcomes)
                    for s in sightings.values()
                ),
                return_exceptions=True,
            )
            for result in results:
                if isinstance(result, Exception):
                    logger.debug(f"Sighting handling failed: {result}")

            await self.check_liveness()
            available = self.available_renderers()
            self._last_scan = {
                "at": time.time(),
                "duration_seconds": round(self._clock() - started, 2),
                "refresh": refresh,
                "replies": dict(replies),
                "reply_total": sum(replies.values()),
                "locations": len(sightings),
                "outcomes": dict(outcomes),
                "error": error,
                "available_renderers": len(available),
            }
            self.manager.log(f"Discovery complete. {len(available)} renderer(s) available")
            return available

    # ------------------------------------------------------------- sightings

    @staticmethod
    def _identity_changed(record: LocationRecord, sighting: Sighting) -> bool:
        if sighting.bootid and record.bootid and sighting.bootid != record.bootid:
            return True
        if sighting.configid and record.configid and sighting.configid != record.configid:
            return True
        return False

    async def _handle_sighting(
        self,
        sighting: Sighting,
        refresh: bool = False,
        force: bool = False,
        outcomes: Optional[Counter] = None,
    ) -> Optional[list[dict]]:
        """Route one sighting: cheap touch, (re-)hydration, or ignore.

        ``refresh`` re-hydrates even an unchanged device; ``force`` also
        ignores the failure cooldown (explicit manual add).
        """
        outcomes = outcomes if outcomes is not None else Counter()
        location = sighting.location
        record = self._locations.get(location)
        if record is None and not sighting.is_renderer:
            outcomes["ignored"] += 1  # some other kind of device; never fetched
            return None

        for udn in sighting.udns:
            previous = self._udn_location.get(udn)
            if previous and previous != location:
                self.manager.log(f"{udn} moved from {previous} to {location}")
            self._udn_location[udn] = location

        if record is not None:
            record.ssdp_udns |= sighting.udns
            unchanged = not self._identity_changed(record, sighting)
            if record.hydrated and unchanged and not refresh and not record.stale:
                if not record.is_renderer:
                    outcomes["not_renderer"] += 1
                    return None
                await self._touch(record, sighting)
                outcomes["cached"] += 1
                return self._infos(record)

        if not force and not self._should_attempt(location, sighting.bootid):
            outcomes["cooldown"] += 1
            return None

        infos = await self.hydrate(
            location,
            bootid=sighting.bootid,
            configid=sighting.configid,
            max_age=sighting.max_age,
            ssdp_udns=sighting.udns,
        )
        outcomes["hydrated" if infos else "failed"] += 1
        return infos

    async def _touch(self, record: LocationRecord, sighting: Optional[Sighting] = None) -> None:
        """Cheap liveness update: no network, no DB unless availability flips."""
        record.last_seen = self._clock()
        record.last_seen_wall = time.time()
        record.byebye = False
        if sighting is not None:
            record.max_age = sighting.max_age or record.max_age
            record.bootid = sighting.bootid or record.bootid
            record.configid = sighting.configid or record.configid
        probe = self._probe_tasks.get(record.location)
        if probe is not None and probe is not asyncio.current_task() and not probe.done():
            self._probe_tasks.pop(record.location, None)
            probe.cancel()
        if not record.available:
            await self._set_available(record, True, "seen again")

    def _infos(self, record: LocationRecord) -> list[dict]:
        return [self.manager.renderers[u] for u in record.udns if u in self.manager.renderers]

    # ------------------------------------------------------------- hydration

    async def hydrate(
        self,
        location: str,
        bootid: Optional[str] = None,
        configid: Optional[str] = None,
        max_age: Optional[int] = None,
        ssdp_udns: Optional[set[str]] = None,
    ) -> Optional[list[dict]]:
        """Fetch one description and register its playable endpoints.

        Concurrent calls for the same URL share one fetch. Returns the
        registered renderer dicts, or None on failure / nothing playable.
        """
        future = self._inflight.get(location)
        if future is None:
            future = asyncio.ensure_future(
                self._hydrate_bounded(location, bootid, configid, max_age, ssdp_udns or set())
            )
            self._inflight[location] = future

            def _done(f: asyncio.Future, loc: str = location) -> None:
                if self._inflight.get(loc) is f:
                    self._inflight.pop(loc, None)

            future.add_done_callback(_done)
        return await asyncio.shield(future)

    async def _hydrate_bounded(self, location, bootid, configid, max_age, ssdp_udns):
        async with self._hydrate_sem:
            try:
                return await asyncio.wait_for(
                    self._hydrate_location(location, bootid, configid, max_age, ssdp_udns),
                    timeout=HYDRATE_DEADLINE_SECONDS,
                )
            except Exception as e:
                if isinstance(e, asyncio.TimeoutError):
                    e = TimeoutError(f"description not hydrated within {HYDRATE_DEADLINE_SECONDS:g}s")
                self._descriptor_failures.append(
                    {"location": location, "error": str(e) or type(e).__name__, "at": time.time()}
                )
                self._track_failure(location, e, bootid)
                return None

    async def _hydrate_location(self, location, bootid, configid, max_age, ssdp_udns):
        await self.manager._ensure_session()
        root = await self.manager._factory.async_create_device(location)
        self.hydration_count += 1

        record = self._locations.get(location) or LocationRecord(location=location)
        self._locations[location] = record
        record.bootid = bootid or record.bootid
        record.configid = configid or record.configid
        record.max_age = max_age or record.max_age
        record.ssdp_udns |= ssdp_udns
        if root.udn:
            record.ssdp_udns.add(root.udn)
            self._udn_location.setdefault(root.udn, location)

        prior = self._failure_state.pop(location, None)  # it answered: reset backoff
        if prior:
            logger.info(f"Renderer at {location} reachable again after {prior['failures']} failure(s)")

        endpoints = playable_endpoints(root)
        if not endpoints:
            record.is_renderer = False
            record.hydrated = True
            record.stale = False
            record.last_seen = self._clock()
            record.last_seen_wall = time.time()
            self.manager.log(f"{location} has no AVTransport service; not a renderer")
            return None

        infos: list[dict] = []
        registered: list[str] = []
        last_error: Optional[Exception] = None
        for node in endpoints:
            udn = node.udn
            if not udn or udn in registered:
                continue
            try:
                infos.append(await self._register_endpoint(node, location))
            except Exception as e:  # one bad endpoint must not hide its siblings
                last_error = e
                logger.debug(f"Could not register {udn} from {location}: {e}")
                continue
            registered.append(udn)
            self._claim_udn(udn, location)
        if not registered:
            raise last_error or RuntimeError(f"{location} has no endpoint with a UDN")

        record.udns = registered
        record.is_renderer = True
        record.hydrated = True
        record.stale = False
        record.byebye = False
        record.last_seen = self._clock()
        record.last_seen_wall = time.time()
        await self._set_available(record, True, "hydrated", persist=False)
        for info in infos:
            self.manager.log(f"Added renderer: {info['friendly_name']} ({info['udn']})")
        return infos

    def _claim_udn(self, udn: str, location: str) -> None:
        """Move an endpoint UDN to ``location``, dropping it from any older record."""
        self._udn_location[udn] = location
        for other in list(self._locations.values()):
            if other.location != location and udn in other.udns:
                other.udns.remove(udn)
                if not other.udns:
                    self._locations.pop(other.location, None)

    async def _register_endpoint(self, node, location: str) -> dict:
        udn = node.udn
        ip = urlparse(location).hostname
        info: dict[str, Any] = {
            "udn": udn,
            "name": node.name or "Unknown Device",  # UI expects 'name' field
            "friendly_name": node.name or "Unknown Device",
            "location": location,
            "ip": ip,
            "device_type": node.device_type,
            "manufacturer": node.manufacturer,
            "model_name": node.model_name,
            "model_number": node.model_number,
            "serial_number": node.serial_number,
            "firmware_version": getattr(node, "firmware_version", None),
            "available": True,
        }
        avt = avtransport_service(node)
        if avt is not None:
            info["control_url"] = avt.control_url
        rc = rendering_control_service(node)
        if rc is not None:
            info["rendering_control_url"] = rc.control_url

        dmr = make_dmr(node)
        info["supports_events"] = True
        info["supports_gapless"] = dmr.has_next_transport_uri

        self.manager.renderers[udn] = info
        self.manager.dmr_devices[udn] = dmr

        supported_mimes = await self.manager.get_supported_protocols(udn)
        if supported_mimes:
            info["supported_mime_types"] = ",".join(sorted(supported_mimes))
        else:
            info["supported_mime_types"] = await self.manager._existing_mime_types(udn) or ""

        icon = _pick_best_icon(_node_icons(node))
        if icon:
            info["icon_url"] = icon.get("url")
            info["icon_mime"] = icon.get("mimetype")
            info["icon_width"] = icon.get("width")
            info["icon_height"] = icon.get("height")
            info["original_icon_url"] = info["icon_url"]

        await self.manager.save_renderer(info)
        if await self.manager._cache_renderer_icon(udn, icon):
            info["icon_url"] = f"/art/renderer/{udn}"
        return info

    async def _add_renderer(
        self, location: str, bootid: Optional[str] = None, configid: Optional[str] = None
    ) -> Optional[list[dict]]:
        """Hydrate ``location`` now. Returns the registered renderers or None."""
        return await self.hydrate(location, bootid=bootid, configid=configid)

    # ---------------------------------------------------------- availability

    async def _set_available(
        self, record: LocationRecord, available: bool, reason: str, persist: bool = True
    ) -> None:
        changed = record.available != available
        record.available = available
        if not available:
            # Whatever we cached may be wrong once it comes back.
            record.stale = True
        for udn in record.udns:
            info = self.manager.renderers.get(udn)
            if info is not None:
                info["available"] = available
        if not changed:
            return
        for udn in record.udns:
            name = (self.manager.renderers.get(udn) or {}).get("friendly_name") or udn
            self._transitions.append(
                {"udn": udn, "name": name, "available": available, "reason": reason, "at": time.time()}
            )
            message = f"Renderer {name} ({udn}) {'available' if available else 'unavailable'}: {reason}"
            self.manager.log(message)
            if available:
                logger.info(message)
            else:
                logger.warning(message)
        if persist and record.udns:
            await self._persist_availability(list(record.udns), available)

    async def _persist_availability(self, udns: list[str], available: bool) -> None:
        try:
            async with db_conn() as db:
                await db.execute(
                    """
                    UPDATE renderer
                    SET available = $2,
                        last_seen_at = CASE WHEN $2 THEN NOW() ELSE last_seen_at END
                    WHERE udn = ANY($1::text[])
                    """,
                    udns,
                    available,
                )
        except Exception as e:
            logger.debug(f"Could not persist renderer availability: {e}")

    def _liveness_due(self, record: LocationRecord, now: float) -> bool:
        if not record.available or not record.udns:
            return False
        if record.byebye:
            return True
        return now > record.last_seen + record.max_age + LIVENESS_GRACE_SECONDS

    async def check_liveness(self) -> None:
        """Probe devices whose lifetime has lapsed; mark the unreachable ones."""
        now = self._clock()
        due = [r for r in list(self._locations.values()) if self._liveness_due(r, now)]
        if due:
            await asyncio.gather(*(self._probe_record(r.location) for r in due))

    def _schedule_probe(
        self,
        location: str,
        delay: float = 0.0,
        rehydrate: bool = False,
        reason: Optional[str] = None,
    ) -> None:
        existing = self._probe_tasks.get(location)
        if existing is not None and not existing.done():
            return

        async def run() -> None:
            if delay:
                await asyncio.sleep(delay)
            await self._probe_record(location, rehydrate=rehydrate, reason=reason)

        task = asyncio.create_task(run())
        self._probe_tasks[location] = task

        def _done(t: asyncio.Task, loc: str = location) -> None:
            if self._probe_tasks.get(loc) is t:
                self._probe_tasks.pop(loc, None)

        task.add_done_callback(_done)

    async def _probe_record(
        self, location: str, rehydrate: bool = False, reason: Optional[str] = None
    ) -> None:
        record = self._locations.get(location)
        if record is None:
            return
        reason = reason or ("byebye" if record.byebye else "lifetime expired")
        if await self._probe_impl(location, PROBE_TIMEOUT_SECONDS):
            if rehydrate:
                await self.hydrate(location)
            else:
                await self._touch(record)
            return
        await self._set_available(record, False, f"{reason}, probe failed")

    async def _http_probe(self, url: str, timeout: float) -> bool:
        try:
            await self.manager._ensure_session()
            async with self.manager._session.get(
                url, timeout=aiohttp.ClientTimeout(total=timeout)
            ) as resp:
                return resp.status == 200
        except Exception:
            return False

    def note_control_failure(self, udn: str) -> None:
        """A control call failed: probe now; re-hydrate if it still answers."""
        location = self._udn_location.get(udn)
        if location and location in self._locations:
            self._schedule_probe(location, rehydrate=True, reason="control call failed")

    def is_available(self, udn: str) -> Optional[bool]:
        """Tracked availability, or None if this UDN is unknown."""
        info = self.manager.renderers.get(udn)
        if info is None:
            return None
        return bool(info.get("available", True))

    def available_renderers(self) -> list[dict]:
        return [r for r in self.manager.renderers.values() if r.get("available", True)]

    # ----------------------------------------------------------- persistence

    async def load_persisted_renderers(self):
        """Load saved renderers (hidden until reachable), then hydrate them."""
        async with db_conn() as db:
            rows = await db.fetch("""
                SELECT r.*, im.artwork_id as has_local_icon
                FROM renderer r
                LEFT JOIN image_map im ON im.entity_type = 'renderer' AND im.entity_id = r.udn AND im.image_type = 'icon'
                WHERE COALESCE(r.kind, 'upnp') = 'upnp'
            """)
        locations: list[str] = []
        for row in rows:
            r = dict(row)
            has_local = r.pop("has_local_icon", None)
            r["original_icon_url"] = r.get("icon_url")
            if has_local:
                r["icon_url"] = f"/art/renderer/{r['udn']}"
            location = r.get("location") or r.get("location_url")
            if not location or r["udn"] in self.manager.renderers:
                continue
            r["location"] = location
            r["available"] = False
            self.manager.renderers[r["udn"]] = r
            record = self._locations.setdefault(location, LocationRecord(location=location))
            record.udns.append(r["udn"])
            record.stale = True
            self._udn_location.setdefault(r["udn"], location)
            if location not in locations:
                locations.append(location)

        due = [loc for loc in locations if self._should_attempt(loc, None)]
        if due:
            await asyncio.gather(*(self.hydrate(loc) for loc in due))
        # Anything still unreachable stays known-but-unavailable in the DB.
        unreachable = [
            udn for udn, info in self.manager.renderers.items() if info.get("available") is False
        ]
        if unreachable:
            await self._persist_availability(unreachable, False)

    # -------------------------------------------------------------- backoff

    def _should_attempt(self, location: str, bootid: Optional[str]) -> bool:
        """Whether a probe of this location is due, given its failure history."""
        state = self._failure_state.get(location)
        if state is None:
            return True
        if state.get("suspended") and bootid and bootid != state.get("bootid"):
            # Device re-announced with a new BOOTID: its UPnP stack restarted,
            # so give it a fresh start.
            self._failure_state.pop(location, None)
            return True
        return state.get("cooldown_until", 0) <= time.time()

    def _track_failure(self, location: str, error: Exception, bootid: Optional[str] = None) -> None:
        now = time.time()
        entry = self._failure_state.get(location) or {}
        failures = entry.get("failures", 0) + 1

        # WARNING on the first failure only; repeats are expected (TVs in standby
        # answer SSDP but refuse HTTP) and logged at DEBUG. The failure state is
        # in-memory, so each process restart logs one line per dead location.
        if failures == 1:
            logger.warning(f"Error adding renderer from {location}: {error}")
            self.manager.log(f"Error adding renderer: {error}")
        else:
            logger.debug(f"Error adding renderer from {location} (failure {failures}): {error}")

        suspended = failures >= _SUSPEND_AFTER_FAILURES
        if suspended:
            cooldown = _SUSPENDED_RETRY_INTERVAL
            if not entry.get("suspended"):
                logger.warning(
                    f"Renderer at {location} failed {failures} times; probing at most "
                    f"every {_SUSPENDED_RETRY_INTERVAL // 3600}h until it re-announces"
                )
        else:
            cooldown = _FAILURE_COOLDOWN_STEPS[min(failures, len(_FAILURE_COOLDOWN_STEPS)) - 1]

        self._failure_state[location] = {
            "failures": failures,
            "cooldown_until": now + cooldown,
            "bootid": bootid if bootid is not None else entry.get("bootid"),
            "suspended": suspended,
        }

    async def verify_device(self, r: Dict[str, Any]) -> bool:
        """Quick check if device is reachable."""
        location = r.get("location") or r.get("location_url")
        if not location:
            return False
        return await self._probe_impl(location, 2.0)

    # ------------------------------------------------- manual add / subnet

    async def _unicast_sightings(self, host: str, timeout: float) -> list[Sighting]:
        """Unicast M-SEARCH straight at ``host`` (IPv4 only)."""
        try:
            if ipaddress.ip_address(host).version != 4:
                return []
        except ValueError:
            return []
        found: Dict[str, Sighting] = {}

        def on_headers(headers: Any) -> None:
            sighting = Sighting.from_headers(headers, source="unicast")
            if sighting is None:
                return
            if sighting.location in found:
                found[sighting.location].merge(sighting)
            else:
                found[sighting.location] = sighting

        try:
            await self._search_impl(
                SEARCH_TARGETS, timeout, on_headers, target_addr=(host, 1900), transmissions=2
            )
        except Exception as e:
            logger.debug(f"Unicast SSDP to {host} failed: {e}")
        return [s for s in found.values() if s.is_renderer]

    async def _probe_host(self, host: str, *, manual: bool) -> Optional[list[dict]]:
        """Find renderers on one host: unicast SSDP first, then guessed URLs."""
        unicast_timeout = MANUAL_UNICAST_TIMEOUT_SECONDS if manual else SUBNET_UNICAST_TIMEOUT_SECONDS
        http_timeout = MANUAL_HTTP_TIMEOUT_SECONDS if manual else SUBNET_HTTP_TIMEOUT_SECONDS

        infos: list[dict] = []
        for sighting in await self._unicast_sightings(host, unicast_timeout):
            result = await self._handle_sighting(sighting, force=manual)
            if result:
                infos.extend(result)
        if infos:
            return infos

        urls = [template.format(host=host) for template in GUESSED_DESCRIPTION_URLS]
        reachable = await asyncio.gather(*(self._probe_impl(url, http_timeout) for url in urls))
        for url, ok in zip(urls, reachable):
            if not ok:
                continue
            result = await self._handle_sighting(
                Sighting(location=url, is_renderer=True, source="guess"), force=manual
            )
            if result:
                return result
        return None

    async def add_device_by_ip(self, address: str) -> Optional[list[dict]]:
        """Manually add a renderer by IP or description URL.

        Returns the registered renderer dicts (one per playable endpoint), or
        None when nothing playable was registered.
        """
        address = (address or "").strip()
        self.manager.log(f"Attempting to add device at {address}...")
        await self.manager._ensure_session()

        if address.lower().startswith(("http://", "https://")):
            infos = await self._handle_sighting(
                Sighting(location=address, is_renderer=True, source="manual"),
                refresh=True,
                force=True,
            )
        else:
            infos = await self._probe_host(address, manual=True)

        if infos:
            names = ", ".join(i.get("friendly_name") or i["udn"] for i in infos)
            self.manager.log(f"Added {len(infos)} renderer(s) from {address}: {names}")
            return infos
        self.manager.log(f"Could not find a UPnP renderer at {address}")
        return None

    async def scan_subnet(self):
        """Sweep the local subnet for renderers. Cancel with cancel_subnet_scan()."""
        if self.is_scanning_subnet:
            return
        self.is_scanning_subnet = True
        self.scan_progress = 0
        self.scan_msg = "Scanning local subnet..."
        task = asyncio.create_task(self._run_subnet_scan())
        self._subnet_task = task

        def _finished(t: asyncio.Task) -> None:
            # Also covers a task cancelled before it ever started running.
            self.is_scanning_subnet = False
            if t.cancelled():
                self.scan_msg = "Scan cancelled"
                self.scan_progress = 100

        task.add_done_callback(_finished)
        try:
            await asyncio.wait({task})
        except asyncio.CancelledError:
            task.cancel()
            raise

    def cancel_subnet_scan(self) -> bool:
        task = self._subnet_task
        if task is None or task.done():
            return False
        task.cancel()
        return True

    async def _run_subnet_scan(self) -> None:
        found = 0
        outcome = "Scan complete"
        try:
            local_ip = self.manager.local_ip
            network, clipped = scan_network(local_ip)
            hosts = [str(h) for h in network.hosts() if str(h) != local_ip]
            total = len(hosts)
            self.scan_total_hosts = total
            if clipped:
                self.manager.log(f"Subnet of {local_ip} is wider than /22; sweeping {network} only")
            self.manager.log(f"Scanning {network} ({total} hosts)")

            known_hosts = {
                urlparse(r.location).hostname
                for r in self._locations.values()
                if r.hydrated and r.is_renderer and r.available
            }
            pending = iter(hosts)
            done = 0

            async def worker() -> None:
                nonlocal done, found
                for host in pending:
                    try:
                        if host not in known_hosts:
                            result = await self._probe_host(host, manual=False)
                            if result:
                                found += len(result)
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        logger.debug(f"Subnet probe of {host} failed: {e}")
                    finally:
                        done += 1
                        self.scan_progress = int(done * 100 / total) if total else 100
                        self.scan_msg = f"Scanned {done}/{total} hosts in {network}"

            await asyncio.gather(*(worker() for _ in range(min(SUBNET_CONCURRENCY, total))))
            outcome = f"Scan complete: {found} new renderer(s) in {network}"
        except asyncio.CancelledError:
            outcome = "Scan cancelled"
            raise
        except Exception as e:
            logger.error(f"Subnet scan error: {e}")
            outcome = f"Scan error: {e}"
        finally:
            self.scan_msg = outcome
            self.scan_progress = 100
            self.manager.log(outcome)

    # ----------------------------------------------------------- diagnostics

    def diagnostics(self) -> dict[str, Any]:
        now_mono = self._clock()
        now = time.time()
        source_ip = getattr(self.manager, "source_ip", None)
        local_ip = getattr(self.manager, "local_ip", None)
        devices = []
        for record in self._locations.values():
            for udn in record.udns or [None]:
                info = self.manager.renderers.get(udn) if udn else None
                devices.append(
                    {
                        "udn": udn,
                        "name": (info or {}).get("friendly_name"),
                        "location": record.location,
                        "available": record.available,
                        "hydrated": record.hydrated,
                        "is_renderer": record.is_renderer,
                        "last_seen_seconds_ago": (
                            round(now_mono - record.last_seen, 1) if record.last_seen else None
                        ),
                        "max_age": record.max_age,
                        "bootid": record.bootid,
                        "configid": record.configid,
                        "byebye": record.byebye,
                    }
                )
        cooldowns = [
            {
                "location": location,
                "failures": state.get("failures"),
                "suspended": bool(state.get("suspended")),
                "bootid": state.get("bootid"),
                "retry_in_seconds": max(0, round(state.get("cooldown_until", 0) - now)),
            }
            for location, state in self._failure_state.items()
        ]
        return {
            "source_ip": source_ip,
            "source_ip_configured": bool(source_ip),
            "stream_ip": local_ip,
            "interface": interface_name(local_ip) if local_ip else None,
            "renderer_base_url": _safe_attr(self.manager, "renderer_base_url"),
            "listener": self._listener_status,
            "search_targets": list(SEARCH_TARGETS),
            "search_transmissions": SEARCH_TRANSMISSIONS,
            "last_scan": dict(self._last_scan),
            "hydrations": self.hydration_count,
            "hydrations_in_flight": len(self._inflight),
            "descriptor_failures": list(self._descriptor_failures),
            "cooldowns": cooldowns,
            "devices": devices,
            "transitions": list(self._transitions),
            "subnet_scan": {
                "running": self.is_scanning_subnet,
                "progress": self.scan_progress,
                "hosts": self.scan_total_hosts,
                "message": self.scan_msg,
            },
        }


def _safe_attr(obj: Any, name: str) -> Any:
    try:
        value = getattr(obj, name, None)
    except Exception:
        return None
    return value if isinstance(value, (str, int, float, bool, type(None))) else None


def _node_icons(node) -> list[dict]:
    """Icons from the endpoint's own description, else from its root's."""
    for candidate in (node, getattr(node, "root_device", None)):
        icons = list(getattr(candidate, "icons", None) or [])
        if icons:
            return [
                {
                    "url": icon.url,
                    "mimetype": icon.mimetype,
                    "width": icon.width,
                    "height": icon.height,
                }
                for icon in icons
                if getattr(icon, "url", None)
            ]
    return []
