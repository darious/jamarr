import logging
import html
from typing import Dict, Any, List, Optional, Set
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from async_upnp_client.exceptions import UpnpError
from app.auth_tokens import create_stream_token
from app.services.renderer.contracts import RendererLoadError, make_renderer_id
from app.services.upnp.protocol_info import (
    NegotiatedFormat,
    default_protocol_info,
    plain_protocol_info,
    mimes_from_protocol_info,
    negotiate_format,
    parse_protocol_info_list,
    split_protocol_info_list,
)
from app.services.upnp.staging import staging, staging_allowed
from app.services.upnp.transport_errors import (
    describe_transport_error,
    is_metadata_fault,
    upnp_error_code,
)

logger = logging.getLogger(__name__)

# Ways of describing one stream to SetAVTransportURI / SetNextAVTransportURI,
# tried in this order when a renderer rejects the description with a fault
# that a different description could fix (see transport_errors):
#   default    -- full DIDL, res@protocolInfo "http-get:*:<mime>:*" (the
#                 wildcard fourth field Jamarr has always sent)
#   advertised -- full DIDL, the renderer's own matching GetProtocolInfo entry
#   minimal    -- title/creator/class/res only: no art, album, duration or size
#   empty      -- no metadata at all; the renderer sniffs the stream
LOAD_STAGES = ("default", "advertised", "minimal", "empty")
MAX_LOAD_ATTEMPTS = len(LOAD_STAGES)


class LoadStrategyMemory:
    """Per renderer and action: the metadata stage that last worked.

    In memory only: it is cheap to rediscover (one extra fault on the first
    load after a restart) and a firmware update may change the answer.
    """

    def __init__(self) -> None:
        self.stages: Dict[tuple, str] = {}
        self.last_errors: Dict[str, Dict[str, Any]] = {}

    def get(self, udn: str, action: str) -> Optional[str]:
        return self.stages.get((udn, action))

    def record(self, udn: str, action: str, stage: str) -> None:
        if stage == "default":
            self.stages.pop((udn, action), None)
        else:
            self.stages[(udn, action)] = stage

    def note_error(
        self, udn: str, action: str, reason: str, detail: str, code: Optional[int]
    ) -> None:
        self.last_errors[udn] = {
            "action": action,
            "reason": reason,
            "detail": detail,
            "upnp_error_code": code,
        }

    def reset(self, udn: Optional[str] = None) -> None:
        if udn is None:
            self.stages.clear()
            self.last_errors.clear()
            return
        for key in [k for k in self.stages if k[0] == udn]:
            del self.stages[key]
        self.last_errors.pop(udn, None)

    def snapshot(self) -> Dict[str, Any]:
        stages: Dict[str, Dict[str, str]] = {}
        for (udn, action), stage in self.stages.items():
            stages.setdefault(udn, {})[action] = stage
        return {"stages": stages, "last_errors": dict(self.last_errors)}


load_strategies = LoadStrategyMemory()


def format_didl_duration(seconds: float | None) -> Optional[str]:
    """Format a duration for DIDL-Lite res@duration (H:MM:SS.mmm)."""
    if not seconds or seconds <= 0:
        return None
    total_ms = round(seconds * 1000)
    ms = total_ms % 1000
    total_s = total_ms // 1000
    h, rem = divmod(total_s, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}.{ms:03d}"


def negotiate_mime(mime_type: str, supported_mimes: Set[str]) -> str:
    """Pick the alias of mime_type the renderer advertises, if it has one."""
    return negotiate_format(mime_type, (), supported_mimes).mime


def with_mime_param(url: str, mime: str) -> str:
    """url plus ``mime=<label>``: /api/stream then serves the label the DIDL names."""
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "mime"]
    query.append(("mime", mime))
    return urlunsplit(parts._replace(query=urlencode(query)))


def build_didl_lite(
    *,
    media_url: str,
    mime_type: str,
    title: str,
    artist: str,
    album: str,
    art_url: Optional[str] = None,
    duration_seconds: float | None = None,
    size_bytes: int | None = None,
    protocol_info: Optional[str] = None,
    minimal: bool = False,
) -> str:
    """DIDL-Lite item for SetAVTransportURI / SetNextAVTransportURI metadata.

    ``protocol_info`` defaults to ``http-get:*:<mime>:*``. ``minimal`` drops
    whatever a picky DIDL parser could choke on: art, album, duration, size.
    """
    title_esc = html.escape(title)
    artist_esc = html.escape(artist)
    album_esc = html.escape(album)
    if protocol_info is None:
        # The minimal stage is the fallback for renderers that object to DLNA
        # fields, so it never carries them.
        protocol_info = plain_protocol_info(mime_type) if minimal else default_protocol_info(mime_type)
    protocol_info_esc = html.escape(protocol_info)
    url_esc = html.escape(media_url, quote=False)

    if minimal:
        return f"""
        <DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/">
            <item id="1" parentID="0" restricted="1">
                <dc:title>{title_esc}</dc:title>
                <dc:creator>{artist_esc}</dc:creator>
                <upnp:class>object.item.audioItem.musicTrack</upnp:class>
                <res protocolInfo="{protocol_info_esc}">{url_esc}</res>
            </item>
        </DIDL-Lite>
        """

    art_element = ""
    if art_url:
        art_element = f"<upnp:albumArtURI>{html.escape(art_url)}</upnp:albumArtURI>"

    # Duration lets renderers show a progress bar without probing the file
    res_attrs = ""
    duration_str = format_didl_duration(duration_seconds)
    if duration_str:
        res_attrs += f' duration="{duration_str}"'
    if size_bytes:
        res_attrs += f' size="{size_bytes}"'

    return f"""
        <DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/" xmlns:dlna="urn:schemas-dlna-org:metadata-1-0/">
            <item id="1" parentID="0" restricted="1">
                <dc:title>{title_esc}</dc:title>
                <dc:creator>{artist_esc}</dc:creator>
                <upnp:artist>{artist_esc}</upnp:artist>
                <upnp:album>{album_esc}</upnp:album>
                <upnp:class>object.item.audioItem.musicTrack</upnp:class>
                {art_element}
                <res protocolInfo="{protocol_info_esc}"{res_attrs}>{url_esc}</res>
            </item>
        </DIDL-Lite>
        """


def _rel_time(seconds: float) -> str:
    """A Seek REL_TIME target, H:MM:SS (UPnP AVTransport's format)."""
    total = int(max(0.0, seconds))
    return f"{total // 3600}:{total % 3600 // 60:02d}:{total % 60:02d}"


async def _transport(dmr, name: str, **args) -> None:
    """Send an AVTransport command straight to the device.

    DmrDevice's async_play/pause/stop/seek_rel_time silently do nothing when
    the device's CurrentTransportActions lacks the plain action name, and
    devices name them their own way (Sonos lists X_DLNA_SeekTime, never
    Seek). UPnP events now keep that list filled in, so going through those
    helpers turned seek into a silent no-op on Sonos. The device decides
    instead: a refusal comes back as a UPnP error.
    """
    action_for = getattr(dmr, "_action", None)
    action = action_for("AVT", name) if action_for else None
    if action is None:
        # Not a full DmrDevice (or no such action): its own helper.
        helper = {"Play": "async_play", "Pause": "async_pause", "Stop": "async_stop"}.get(name)
        if helper is None:
            raise UpnpError(f"Missing action AVT/{name}")
        await getattr(dmr, helper)()
        return
    if name == "Play":
        args.setdefault("Speed", "1")
    await action.async_call(InstanceID=0, **args)


class UPnPDeviceControl:
    def __init__(self, manager):
        self.manager = manager
        # udn -> TrackURI from the last GetPositionInfo, for transition
        # detection (the renderer's current track vs the staged one).
        self._track_uris: Dict[str, Optional[str]] = {}

    async def get_supported_protocols(self, udn: str, dmr=None) -> Set[str]:
        """Bare MIME types the device advertises (legacy view of the Sink list)."""
        entries = await self.get_sink_protocol_info(udn, dmr)
        return mimes_from_protocol_info(parse_protocol_info_list(entries))

    async def get_sink_protocol_info(self, udn: str, dmr=None) -> List[str]:
        """The device's GetProtocolInfo Sink entries, complete and verbatim.

        All four fields are kept (MIME parameters, DLNA.ORG_PN/OP/FLAGS), in
        the device's order. Empty if the device has no ConnectionManager or
        does not answer.
        """
        dmr = dmr or self.manager.dmr_devices.get(udn)
        if not dmr:
            return []

        device = dmr.device

        # Find ConnectionManager service
        cm_service = None
        for service in device.services.values():
            if "ConnectionManager" in service.service_type:
                cm_service = service
                break

        if not cm_service:
            logger.debug(f"No ConnectionManager service found for {udn}")
            return []

        try:
            action = cm_service.action("GetProtocolInfo")
            result = await action.async_call()

            # Sink: what the device can play
            raw_entries = split_protocol_info_list(result.get("Sink", ""))
            # Keep only well-formed entries, verbatim; drop exact duplicates.
            entries: List[str] = []
            for entry in parse_protocol_info_list(raw_entries):
                if entry.raw not in entries:
                    entries.append(entry.raw)
            logger.debug(f"Device {udn} advertises {len(entries)} sink protocolInfo entries")
            return entries

        except Exception as e:
            logger.debug(f"Error querying protocols for {udn}: {e}")
            return []

    def negotiated_format(self, udn: str, mime: Optional[str]) -> NegotiatedFormat:
        """The label/protocolInfo to describe a stream of ``mime`` with on udn."""
        renderer_info = self.manager.renderers.get(udn, {})
        entries = parse_protocol_info_list(renderer_info.get("sink_protocol_info") or [])
        legacy = renderer_info.get("supported_mime_types") or ""
        if isinstance(legacy, str):
            legacy = [m for m in legacy.split(",") if m]
        return negotiate_format(mime, entries, legacy)

    def _media_for_track(
        self,
        udn: str,
        track_id: int,
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Stream URL, negotiated format and DIDL-Lite variants for one track on udn.

        Shared by SetAVTransportURI (play_track) and SetNextAVTransportURI
        (set_next_track) so a staged track is described exactly like a
        loaded one.
        """
        # Prefer the URL the renderer stack already built: it carries the
        # loudness-normalization claims in its stream token, which a token
        # minted here would not. The fallback keeps legacy direct calls working.
        # Either way renderers fetch via the header-recasing proxy, not uvicorn
        # directly (see stream_proxy.py).
        media_url = metadata.get("stream_url")
        if not media_url:
            stream_token = create_stream_token(track_id, user_id=metadata.get("user_id"))
            media_url = (
                f"{self.manager.renderer_base_url}/api/stream/{track_id}"
                f"?token={stream_token}"
            )

        renderer_info = self.manager.renderers.get(udn, {})
        # The plan's MIME as /api/stream serves it, parameters included:
        # audio/L16 without its rate/channels is not the stream's
        # Content-Type, and could match an advertised entry of another rate.
        stream_mime = (metadata.get("mime") or "").strip() or "audio/flac"
        negotiated = self.negotiated_format(udn, stream_mime)
        mime_type = negotiated.mime
        if mime_type != stream_mime:
            # A relabel within the alias family: the stream endpoint must send
            # the same name in Content-Type as the DIDL does.
            media_url = with_mime_param(media_url, mime_type)

        # Build art URL if available
        art_url = None
        if metadata.get("art_sha1"):
            art_url = (
                f"{self.manager.renderer_base_url}/art/file/{metadata['art_sha1']}"
                f"?max_size=600"
            )

        title = metadata.get("title", "Unknown Track")
        artist = metadata.get("artist", "Unknown Artist")
        album = metadata.get("album", "Unknown Album")
        didl_args: Dict[str, Any] = dict(
            media_url=media_url,
            mime_type=mime_type,
            title=title,
            artist=artist,
            album=album,
            art_url=art_url,
            duration_seconds=metadata.get("duration_seconds"),
            size_bytes=metadata.get("size_bytes"),
        )
        # One description per load stage (see LOAD_STAGES).
        exact = negotiated.exact_protocol_info
        variants: Dict[str, str] = {"default": build_didl_lite(**didl_args)}
        if exact:
            variants["advertised"] = build_didl_lite(**didl_args, protocol_info=exact)
        variants["minimal"] = build_didl_lite(**didl_args, protocol_info=exact, minimal=True)
        variants["empty"] = ""
        return {
            "media_url": media_url,
            "mime_type": mime_type,
            "stream_mime_type": stream_mime,
            "negotiated": negotiated,
            "title": title,
            "artist": artist,
            "didl": variants["default"],
            "didl_variants": variants,
            "renderer_info": renderer_info,
        }

    @staticmethod
    def _load_plan(udn: str, action: str, variants: Dict[str, str]) -> List[str]:
        """Stages to try, the one that last worked first, at most MAX_LOAD_ATTEMPTS."""
        order = [stage for stage in LOAD_STAGES if stage in variants]
        remembered = load_strategies.get(udn, action)
        if remembered in order:
            order.remove(remembered)
            order.insert(0, remembered)
        return order[:MAX_LOAD_ATTEMPTS]

    async def _send_with_fallback(
        self, udn: str, action: str, media: Dict[str, Any], send
    ) -> str:
        """Run ``send(meta_data)`` through the load stages; return the one that worked.

        Retries only faults another description might fix
        (``transport_errors.is_metadata_fault``); any other fault, or the last
        attempt's, is raised unchanged.
        """
        variants = media["didl_variants"]
        plan = self._load_plan(udn, action, variants)
        for attempt, stage in enumerate(plan, start=1):
            try:
                await send(variants[stage])
            except Exception as exc:
                retry = attempt < len(plan) and is_metadata_fault(exc)
                logger.warning(
                    f"[UPnP] {action} on {udn} failed with {stage} metadata "
                    f"(attempt {attempt}/{len(plan)}, {media['mime_type']}): {exc}"
                    + ("; retrying with a different description" if retry else "")
                )
                if not retry:
                    raise
                continue
            if attempt > 1 or stage != "default":
                logger.info(f"[UPnP] {action} on {udn} accepted {stage} metadata")
            load_strategies.record(udn, action, stage)
            return stage
        raise RuntimeError("empty load plan")  # pragma: no cover - plan is never empty

    def _load_error(
        self, udn: str, action: str, exc: BaseException, media: Dict[str, Any]
    ) -> RendererLoadError:
        """An actionable RendererLoadError for a failed transport action."""
        renderer_info = media.get("renderer_info") or {}
        base = getattr(self.manager, "renderer_base_url", None)
        stream_host = urlsplit(base).netloc if isinstance(base, str) and base else None
        negotiated = media.get("negotiated")
        reason, detail = describe_transport_error(
            exc,
            action=action,
            renderer_name=renderer_info.get("friendly_name") or "Renderer",
            mime_type=media.get("mime_type"),
            advertised_support=negotiated.advertised_support if negotiated else None,
            stream_host=stream_host,
        )
        load_strategies.note_error(udn, action, reason, detail, upnp_error_code(exc))
        logger.warning(f"[UPnP] {action} on {udn} failed: {reason}: {detail}")
        return RendererLoadError(make_renderer_id("upnp", udn), reason, detail)

    async def play_track(
        self,
        track_id: int,
        track_path: str,
        metadata: Dict[str, Any],
        username: str = None,
    ):
        """
        Play a track on the active renderer.
        """
        if not self.manager.active_renderer:
            raise ValueError("No active renderer set")

        udn = self.manager.active_renderer
        dmr = self.manager.dmr_devices.get(udn)
        if not dmr:
            raise ValueError(f"DMR device not found for {udn}")

        media = self._media_for_track(udn, track_id, metadata)
        title, artist, mime_type = media["title"], media["artist"], media["mime_type"]

        # Get renderer info
        renderer_info = media["renderer_info"]
        friendly_name = renderer_info.get("friendly_name", "Unknown")
        location = renderer_info.get("location", "")
        renderer_ip = (
            location.split("//")[1].split(":")[0] if "//" in location else "Unknown"
        )

        # Log
        log_parts = [
            f"Playing: {track_path} : {title} by {artist} ({mime_type}) on {friendly_name}"
        ]
        if renderer_ip != "Unknown":
            log_parts.append(f"({renderer_ip})")
        if username:
            log_parts.append(f"requested by {username}")
        logger.info(" ".join(log_parts))

        # A new current URI supersedes whatever was staged as next; the
        # monitor re-stages once this track is confirmed playing.
        staging.forget(udn)

        # Set transport URI
        async def send(meta_data: str) -> None:
            await dmr.async_set_transport_uri(
                media_url=media["media_url"], media_title=title, meta_data=meta_data
            )

        try:
            await self._send_with_fallback(udn, "SetAVTransportURI", media, send)
        except (UpnpError, OSError) as exc:
            raise self._load_error(udn, "SetAVTransportURI", exc, media) from exc

        # Wait for device
        await dmr.async_wait_for_can_play(max_wait_time=5)

        # Start playback
        try:
            await _transport(dmr, "Play")
        except (UpnpError, OSError) as e:
            if upnp_error_code(e) == 701 or (isinstance(e, UpnpError) and "701" in str(e)):
                logger.info("Device already playing, ignoring play command")
            else:
                raise self._load_error(udn, "Play", e, media) from e

    def next_track_staging_allowed(self, udn: str) -> bool:
        """Whether to stage the next track on udn (config, faults, advert)."""
        dmr = self.manager.dmr_devices.get(udn)
        if not dmr:
            return False
        try:
            advertised = bool(dmr.has_next_transport_uri)
        except Exception:
            advertised = False
        return staging_allowed(udn, advertised)

    async def set_next_track(
        self,
        udn: str,
        track_id: int,
        metadata: Dict[str, Any],
    ) -> str:
        """Stage track_id as udn's next URI (SetNextAVTransportURI).

        Returns the URI staged. Metadata faults go through the same bounded
        description ladder as a load; whatever the device raised last is
        re-raised unchanged, and the caller decides whether that disables
        staging.
        """
        dmr = self.manager.dmr_devices.get(udn)
        if not dmr:
            raise ValueError(f"DMR device not found for {udn}")
        media = self._media_for_track(udn, track_id, metadata)

        async def send(meta_data: str) -> None:
            await dmr.async_set_next_transport_uri(
                media_url=media["media_url"],
                media_title=media["title"],
                meta_data=meta_data,
            )

        await self._send_with_fallback(udn, "SetNextAVTransportURI", media, send)
        logger.info(
            f"[Gapless] Staged next track on {udn}: {media['title']} by "
            f"{media['artist']} ({media['mime_type']})"
        )
        return media["media_url"]

    async def clear_next_track(self, udn: str) -> None:
        """Best-effort: empty udn's NextAVTransportURI if we may have set one."""
        if not staging.get(udn) and udn not in staging.needs_clear:
            return
        dmr = self.manager.dmr_devices.get(udn)
        ok = False
        try:
            # Also when staging has just been disabled: the device may still
            # hold the URI and would otherwise roll into it.
            if dmr:
                await dmr.async_set_next_transport_uri(
                    media_url="", media_title="", meta_data=""
                )
                ok = True
                logger.info(f"[Gapless] Cleared staged next track on {udn}")
        except Exception as exc:
            # Plenty of renderers reject an empty NextURI; nothing to fall
            # back to, and it does not mean staging itself is broken.
            logger.debug(f"Clearing next URI on {udn} failed: {exc}")
        finally:
            staging.cleared(udn, ok=ok)

    def current_track_uri(self, udn: str) -> Optional[str]:
        """TrackURI from the last GetPositionInfo answered by udn."""
        return self._track_uris.get(udn)

    async def stop_renderer(self, udn: str) -> None:
        """Stop udn's transport (used when it rolled into a dropped track)."""
        dmr = self.manager.dmr_devices.get(udn)
        if dmr:
            await _transport(dmr, "Stop")

    async def pause(self):
        """Pause playback on active renderer."""
        if not self.manager.active_renderer:
            return

        dmr = self.manager.dmr_devices.get(self.manager.active_renderer)
        if dmr:
            await _transport(dmr, "Pause")
            self.manager.log("Playback paused")

    async def stop(self):
        """Stop the active renderer (queue cleared or stopped)."""
        if not self.manager.active_renderer:
            return

        dmr = self.manager.dmr_devices.get(self.manager.active_renderer)
        if dmr:
            await _transport(dmr, "Stop")
            self.manager.log("Playback stopped")

    async def resume(self):
        """Resume playback on active renderer."""
        if not self.manager.active_renderer:
            return

        dmr = self.manager.dmr_devices.get(self.manager.active_renderer)
        if dmr:
            await _transport(dmr, "Play")
            self.manager.log("Playback resumed")

    async def seek(self, target_seconds: float):
        """Seek to a specific time position."""
        if not self.manager.active_renderer:
            return

        dmr = self.manager.dmr_devices.get(self.manager.active_renderer)
        if dmr:
            target = _rel_time(target_seconds)
            await _transport(dmr, "Seek", Unit="REL_TIME", Target=target)
            self.manager.log(f"Seeked to {target}")

    async def set_volume(self, volume: int) -> None:
        """Set volume (0-100)."""
        if not self.manager.active_renderer:
            raise ValueError("No active renderer set")

        dmr = self.manager.dmr_devices.get(self.manager.active_renderer)
        if not dmr:
            raise ValueError(f"DMR device not found for {self.manager.active_renderer}")

        # No fallback path here on purpose. There used to be one that called
        # dmr._action("RenderingControl", "SetVolume"), but _action resolves its
        # first argument through _SERVICE_TYPES, whose keys are abbreviations
        # ("RC"). "RenderingControl" is not a key, so that lookup returned None
        # on every device and raised a fabricated "action not found" -- which
        # masked the real failure and read as a device capability report.
        # async_set_volume_level already performs exactly that call, correctly.
        volume_level = volume / 100.0  # device API is 0.0-1.0
        await dmr.async_set_volume_level(volume_level)
        self.manager.log(f"Volume set to {volume}")

    def can_mute(self, udn: str) -> bool:
        """Whether udn's RenderingControl has a SetMute action (not merely a
        Mute state variable, which is all DmrDevice.has_volume_mute checks)."""
        dmr = self.manager.dmr_devices.get(udn)
        if dmr is None:
            return False
        try:
            # "RC" is async_upnp_client's key for RenderingControl.
            return dmr._action("RC", "SetMute") is not None
        except Exception:
            return False

    async def set_mute(self, muted: bool) -> None:
        """RenderingControl SetMute on the active renderer."""
        if not self.manager.active_renderer:
            raise ValueError("No active renderer set")
        dmr = self.manager.dmr_devices.get(self.manager.active_renderer)
        if not dmr:
            raise ValueError(f"DMR device not found for {self.manager.active_renderer}")
        await dmr.async_mute_volume(bool(muted))
        self.manager.log(f"Mute set to {bool(muted)}")

    async def get_volume(self, udn: Optional[str] = None) -> Optional[int]:
        """Read the renderer's current volume as 0-100 percent, or None.

        Scaled by the device's declared Volume range so devices with a
        non-100 maximum still map to percent correctly.
        """
        target_udn = udn or self.manager.active_renderer
        if not target_udn:
            return None
        dmr = self.manager.dmr_devices.get(target_udn)
        if not dmr:
            return None
        try:
            # "RC", not "RenderingControl": _action keys are the abbreviations
            # (see set_volume); the long name never resolves.
            action = dmr._action("RC", "GetVolume")
            if not action:
                return None
            result = await action.async_call(InstanceID=0, Channel="Master")
            current = result.get("CurrentVolume")
            if current is None:
                return None
            max_volume = 100
            try:
                state_var = dmr._state_variable("RC", "Volume")
                if state_var is not None and state_var.max_value:
                    max_volume = int(state_var.max_value) or 100
            except Exception:
                pass
            return max(0, min(100, round(int(current) * 100 / max_volume)))
        except Exception as exc:
            logger.debug(f"get_volume failed for {target_udn}: {exc}")
            return None

    async def get_position(self, udn: Optional[str] = None):
        """Get current playback position in seconds."""
        target_udn = udn or self.manager.active_renderer
        if not target_udn:
            return 0, 0

        dmr = self.manager.dmr_devices.get(target_udn)
        if not dmr:
            logger.debug(f"get_position: DMR not found for {target_udn}")
            return 0, 0

        try:
            # DmrDevice doesn't have a helper for GetPositionInfo, call action directly
            # This is standard AVTransport action
            action = dmr._action("AVT", "GetPositionInfo")
            if not action:
                 logger.warning(f"get_position({target_udn}): AVT/GetPositionInfo action not found")
                 return 0, 0

            result = await action.async_call(InstanceID=0)
            
            self._track_uris[target_udn] = result.get("TrackURI") or None
            rel_time = result.get("RelTime", "0:00:00")
            track_duration = result.get("TrackDuration", "0:00:00")

            def parse_time(t_str):
                # H+:MM:SS[.F+]: Sony Bravias report milliseconds
                # ("0:00:15.618"), which an int() parse read as 0 -- the
                # position never moved, so the next track was never staged
                # and the end of every track looked like a failed start.
                from app.services.upnp.events import parse_upnp_duration

                seconds = parse_upnp_duration(t_str)
                return int(seconds) if seconds else 0

            p_secs = parse_time(rel_time)
            d_secs = parse_time(track_duration)
            
            logger.info(f"get_position({target_udn}) -> {rel_time} ({p_secs}s) / {track_duration} ({d_secs}s)")
            return p_secs, d_secs

        except Exception as e:
            self._track_uris.pop(target_udn, None)
            logger.warning(f"get_position({target_udn}) failed: {e}")
            return 0, 0

    async def get_transport_info(self, udn: Optional[str] = None):
        """Get transport state (PLAYING, STOPPED, etc)."""
        target_udn = udn or self.manager.active_renderer
        if not target_udn:
            return "STOPPED"

        dmr = self.manager.dmr_devices.get(target_udn)
        if not dmr:
            logger.debug(f"get_transport_info: DMR not found for {target_udn}")
            return "STOPPED"

        try:
            # DmrDevice uses properties populate by async_update / eventing
            await dmr.async_update()
            state_enum = dmr.transport_state
            
            if state_enum:
                # Convert Enum to string (e.g. TransportState.PLAYING -> "PLAYING")
                state = state_enum.name
            else:
                state = "STOPPED"

            logger.info(f"get_transport_info({target_udn}) -> {state}")
            return state
        except Exception as e:
            logger.warning(f"get_transport_info({target_udn}) failed: {e}")
            return "STOPPED"
