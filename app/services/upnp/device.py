import logging
import html
from typing import Dict, Any, Optional, Set
from async_upnp_client.exceptions import UpnpError
from app.auth_tokens import create_stream_token
from app.services.upnp.staging import staging, staging_allowed

logger = logging.getLogger(__name__)


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
    if mime_type == "audio/flac":
        if "audio/flac" in supported_mimes:
            logger.debug("Device supports audio/flac")
            return "audio/flac"
        if "audio/x-flac" in supported_mimes:
            logger.debug("Device supports audio/x-flac")
            return "audio/x-flac"
        logger.debug("Device protocols unknown, using audio/flac as default")
        return "audio/flac"
    if mime_type == "audio/mp4":
        if "audio/mp4" in supported_mimes:
            return "audio/mp4"
        if "audio/x-m4a" in supported_mimes:
            return "audio/x-m4a"
    return mime_type


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
) -> str:
    """DIDL-Lite item for SetAVTransportURI / SetNextAVTransportURI metadata."""
    title_esc = html.escape(title)
    artist_esc = html.escape(artist)
    album_esc = html.escape(album)

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
                <res protocolInfo="http-get:*:{mime_type}:*"{res_attrs}>{media_url}</res>
            </item>
        </DIDL-Lite>
        """


class UPnPDeviceControl:
    def __init__(self, manager):
        self.manager = manager
        # udn -> TrackURI from the last GetPositionInfo, for transition
        # detection (the renderer's current track vs the staged one).
        self._track_uris: Dict[str, Optional[str]] = {}

    async def get_supported_protocols(self, udn: str, dmr=None) -> Set[str]:
        """
        Query device's supported MIME types via GetProtocolInfo.
        """
        dmr = dmr or self.manager.dmr_devices.get(udn)
        if not dmr:
            return set()

        device = dmr.device

        # Find ConnectionManager service
        cm_service = None
        for service in device.services.values():
            if "ConnectionManager" in service.service_type:
                cm_service = service
                break

        if not cm_service:
            logger.debug(f"No ConnectionManager service found for {udn}")
            return set()

        try:
            action = cm_service.action("GetProtocolInfo")
            result = await action.async_call()

            # Parse Sink protocols (what the device can play)
            sink = result.get("Sink", "")
            if not sink:
                return set()

            # Extract unique MIME types
            mime_types = set()
            protocols = sink.split(",")
            for proto in protocols:
                parts = proto.split(":")
                if len(parts) >= 3:
                    mime = parts[2]
                    if mime and mime != "*":
                        mime_types.add(mime)

            logger.debug(f"Device {udn} supports {len(mime_types)} MIME types")
            return mime_types

        except Exception as e:
            logger.debug(f"Error querying protocols for {udn}: {e}")
            return set()

    def _media_for_track(
        self,
        udn: str,
        track_id: int,
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Stream URL, negotiated MIME and DIDL-Lite for one track on udn.

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

        # Get supported MIME types from renderer info
        renderer_info = self.manager.renderers.get(udn, {})
        supported_mimes_str = renderer_info.get("supported_mime_types", "")
        supported_mimes = (
            set(supported_mimes_str.split(",")) if supported_mimes_str else set()
        )
        mime_type = negotiate_mime(metadata.get("mime", "audio/flac"), supported_mimes)

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
        didl_lite = build_didl_lite(
            media_url=media_url,
            mime_type=mime_type,
            title=title,
            artist=artist,
            album=album,
            art_url=art_url,
            duration_seconds=metadata.get("duration_seconds"),
            size_bytes=metadata.get("size_bytes"),
        )
        return {
            "media_url": media_url,
            "mime_type": mime_type,
            "title": title,
            "artist": artist,
            "didl": didl_lite,
            "renderer_info": renderer_info,
        }

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
        await dmr.async_set_transport_uri(
            media_url=media["media_url"], media_title=title, meta_data=media["didl"]
        )

        # Wait for device
        await dmr.async_wait_for_can_play(max_wait_time=5)

        # Start playback
        try:
            await dmr.async_play()
        except UpnpError as e:
            if "701" in str(e):
                logger.info("Device already playing, ignoring play command")
            else:
                raise

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

        Returns the URI staged. Raises whatever the device raised; the caller
        decides whether that disables staging.
        """
        dmr = self.manager.dmr_devices.get(udn)
        if not dmr:
            raise ValueError(f"DMR device not found for {udn}")
        media = self._media_for_track(udn, track_id, metadata)
        await dmr.async_set_next_transport_uri(
            media_url=media["media_url"],
            media_title=media["title"],
            meta_data=media["didl"],
        )
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
        try:
            if dmr and not staging.is_disabled(udn):
                await dmr.async_set_next_transport_uri(
                    media_url="", media_title="", meta_data=""
                )
                logger.info(f"[Gapless] Cleared staged next track on {udn}")
        except Exception as exc:
            # Plenty of renderers reject an empty NextURI; nothing to fall
            # back to, and it does not mean staging itself is broken.
            logger.debug(f"Clearing next URI on {udn} failed: {exc}")
        finally:
            staging.cleared(udn)

    def current_track_uri(self, udn: str) -> Optional[str]:
        """TrackURI from the last GetPositionInfo answered by udn."""
        return self._track_uris.get(udn)

    async def stop_renderer(self, udn: str) -> None:
        """Stop udn's transport (used when it rolled into a dropped track)."""
        dmr = self.manager.dmr_devices.get(udn)
        if dmr:
            await dmr.async_stop()

    async def pause(self):
        """Pause playback on active renderer."""
        if not self.manager.active_renderer:
            return

        dmr = self.manager.dmr_devices.get(self.manager.active_renderer)
        if dmr:
            await dmr.async_pause()
            self.manager.log("Playback paused")

    async def resume(self):
        """Resume playback on active renderer."""
        if not self.manager.active_renderer:
            return

        dmr = self.manager.dmr_devices.get(self.manager.active_renderer)
        if dmr:
            await dmr.async_play()
            self.manager.log("Playback resumed")

    async def seek(self, target_seconds: float):
        """Seek to a specific time position."""
        if not self.manager.active_renderer:
            return

        dmr = self.manager.dmr_devices.get(self.manager.active_renderer)
        if dmr:
            from datetime import timedelta

            target = timedelta(seconds=max(0.0, target_seconds))
            await dmr.async_seek_rel_time(target)
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
            action = dmr._action("RenderingControl", "GetVolume")
            if not action:
                return None
            result = await action.async_call(InstanceID=0, Channel="Master")
            current = result.get("CurrentVolume")
            if current is None:
                return None
            max_volume = 100
            try:
                state_var = dmr._state_variable("RenderingControl", "Volume")
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
                try:
                    parts = list(map(int, t_str.split(":")))
                    if len(parts) == 3:
                        return parts[0] * 3600 + parts[1] * 60 + parts[2]
                    return 0
                except ValueError:
                    return 0

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
