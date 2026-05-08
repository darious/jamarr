import logging
import html
from typing import Dict, Any, Optional, Set
from async_upnp_client.exceptions import UpnpError
from app.auth_tokens import create_stream_token

logger = logging.getLogger(__name__)

class UPnPDeviceControl:
    def __init__(self, manager):
        self.manager = manager

    async def get_supported_protocols(self, udn: str) -> Set[str]:
        """
        Query device's supported MIME types via GetProtocolInfo.
        """
        dmr = self.manager.dmr_devices.get(udn)
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

        dmr = self.manager.dmr_devices.get(self.manager.active_renderer)
        if not dmr:
            raise ValueError(f"DMR device not found for {self.manager.active_renderer}")

        # Build media URL with a short-lived stream token
        stream_token = create_stream_token(track_id, user_id=metadata.get("user_id"))
        media_url = (
            f"{self.manager.base_url}/api/stream/{track_id}"
            f"?token={stream_token}"
        )

        # Get MIME type from metadata
        mime_type = metadata.get("mime", "audio/flac")

        # Get supported MIME types from renderer info
        renderer_info = self.manager.renderers.get(self.manager.active_renderer, {})
        supported_mimes_str = renderer_info.get("supported_mime_types", "")
        supported_mimes = (
            set(supported_mimes_str.split(",")) if supported_mimes_str else set()
        )

        # Choose the best MIME type
        if mime_type == "audio/flac":
            if "audio/flac" in supported_mimes:
                mime_type = "audio/flac"
                logger.debug("Device supports audio/flac")
            elif "audio/x-flac" in supported_mimes:
                mime_type = "audio/x-flac"
                logger.debug("Device supports audio/x-flac")
            else:
                mime_type = "audio/flac"
                logger.debug("Device protocols unknown, using audio/flac as default")
        elif mime_type == "audio/mp4":
            if "audio/mp4" in supported_mimes:
                mime_type = "audio/mp4"
            elif "audio/x-m4a" in supported_mimes:
                mime_type = "audio/x-m4a"

        # Build art URL if available
        art_url = None
        if metadata.get("art_sha1"):
            art_url = f"{self.manager.base_url}/art/file/{metadata['art_sha1']}?max_size=600"

        # Extract metadata fields
        title = metadata.get("title", "Unknown Track")
        artist = metadata.get("artist", "Unknown Artist")
        album = metadata.get("album", "Unknown Album")

        # Get renderer info
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

        # Construct DIDL-Lite XML
        title_esc = html.escape(title)
        artist_esc = html.escape(artist)
        album_esc = html.escape(album)

        art_element = ""
        if art_url:
            art_element = f"<upnp:albumArtURI>{html.escape(art_url)}</upnp:albumArtURI>"

        didl_lite = f"""
        <DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/" xmlns:dlna="urn:schemas-dlna-org:metadata-1-0/">
            <item id="1" parentID="0" restricted="1">
                <dc:title>{title_esc}</dc:title>
                <dc:creator>{artist_esc}</dc:creator>
                <upnp:artist>{artist_esc}</upnp:artist>
                <upnp:album>{album_esc}</upnp:album>
                <upnp:class>object.item.audioItem.musicTrack</upnp:class>
                {art_element}
                <res protocolInfo="http-get:*:{mime_type}:*">{media_url}</res>
            </item>
        </DIDL-Lite>
        """

        # Set transport URI
        await dmr.async_set_transport_uri(
            media_url=media_url, media_title=title, meta_data=didl_lite
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

        try:
            # Convert from 0-100 to 0.0-1.0 range
            volume_level = volume / 100.0
            await dmr.async_set_volume_level(volume_level)
            self.manager.log(f"Volume set to {volume}")
            return
        except (UpnpError, AttributeError) as exc:
            logger.debug("async_set_volume_level failed for %s: %s, trying direct action", self.manager.active_renderer, exc)

        # Fallback to direct action call
        action = dmr._action("RenderingControl", "SetVolume")
        if not action:
            raise UpnpError("RenderingControl/SetVolume action not found")

        await action.async_call(InstanceID=0, Channel="Master", DesiredVolume=volume)
        self.manager.log(f"Volume set to {volume} via RenderingControl")

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
