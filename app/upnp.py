import asyncio
import logging
from typing import Dict, Any, Optional, Callable
from urllib.parse import urlparse
from xml.sax.saxutils import escape
import aiohttp

from async_upnp_client.client_factory import UpnpFactory
from async_upnp_client.client import UpnpDevice, UpnpService
from async_upnp_client.profiles.dlna import DmrDevice
from async_upnp_client.search import async_search
from async_upnp_client.ssdp import SSDP_ST_ALL
from async_upnp_client.aiohttp import AiohttpRequester, AiohttpSessionRequester
from async_upnp_client.exceptions import UpnpError, UpnpConnectionError
from async_upnp_client.utils import CaseInsensitiveDict

from app.db import get_db
import aiosqlite

logger = logging.getLogger(__name__)

# Search target for MediaRenderer devices
SSDP_TARGET_MEDIA_RENDERER = "urn:schemas-upnp-org:device:MediaRenderer:1"



class UPnPManager:
    """
    UPnP/DLNA Media Renderer Manager using async-upnp-client library.
    
    Manages discovery, control, and state management of UPnP media renderers.
    Maintains backward compatibility with existing player API.
    """
    
    _instance = None
    
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def __init__(self):
        self.debug_log = []
        self.renderers: Dict[str, Dict[str, Any]] = {}  # udn -> renderer info
        self.dmr_devices: Dict[str, DmrDevice] = {}  # udn -> DmrDevice instance
        self.active_renderer = None  # udn
        self.local_ip = self._get_local_ip()
        self.base_url = f"http://{self.local_ip}:8111"
        
        # Discovery state
        self._discovery_task: Optional[asyncio.Task] = None
        self._running = False
        
        # Subnet scanning state
        self.is_scanning_subnet = False
        self.scan_msg = ""
        self.scan_progress = 0
        
        # HTTP session for library
        self._session: Optional[aiohttp.ClientSession] = None
        self._requester: Optional[AiohttpSessionRequester] = None
        self._factory: Optional[UpnpFactory] = None
    
    def _get_local_ip(self) -> str:
        """Get local IP address for media streaming URLs."""
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"
    
    def log(self, msg: str):
        """Add message to debug log (limited to last 100 entries)."""
        logger.debug(msg)
        self.debug_log.append(msg)
        if len(self.debug_log) > 100:
            self.debug_log.pop(0)
    
    async def _ensure_session(self):
        """Ensure HTTP session and requester are initialized."""
        if self._session is None:
            self._session = aiohttp.ClientSession()
            self._requester = AiohttpSessionRequester(self._session, with_sleep=True)
            self._factory = UpnpFactory(self._requester)
    
    def start_background_scan(self):
        """Start background discovery loop."""
        if not self._running:
            self._running = True
            self._discovery_task = asyncio.create_task(self._discovery_loop())
            self.log("Started background UPnP discovery")
    
    async def stop_background_scan(self):
        """Stop background discovery loop."""
        self._running = False
        if self._discovery_task:
            self._discovery_task.cancel()
            try:
                await asyncio.wait_for(self._discovery_task, timeout=2.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
        
        # Cleanup HTTP session
        if self._session:
            try:
                await asyncio.wait_for(self._session.close(), timeout=2.0)
            except Exception as e:
                logger.debug(f"Error closing UPnP session: {e}")
            
            self._session = None
            self._requester = None
            self._factory = None
        
        self.log("Stopped background UPnP discovery")
    
    async def _discovery_loop(self):
        """Periodic discovery loop to find and maintain renderer list."""
        await self.load_persisted_renderers()
        
        while self._running:
            try:
                await self.discover(timeout=3)
                await asyncio.sleep(30)  # Discover every 30 seconds
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Discovery loop error: {e}")
                await asyncio.sleep(30)
    
    async def discover(self, timeout=5):
        """
        Discover UPnP Media Renderers on the network using async_search.
        
        Args:
            timeout: Discovery timeout in seconds
        """
        await self._ensure_session()
        
        self.log(f"Starting UPnP discovery (timeout={timeout}s)...")
        
        discovered_locations = []
        
        async def search_callback(headers: CaseInsensitiveDict):
            """Callback for each discovered device."""
            location = headers.get("location") or headers.get("LOCATION")
            st = headers.get("st") or headers.get("ST")
            
            # Filter for MediaRenderer devices
            if location and st and "MediaRenderer" in st:
                if location not in discovered_locations:
                    discovered_locations.append(location)
        
        try:
            # Perform search with callback
            await async_search(
                async_callback=search_callback,
                timeout=timeout,
                search_target=SSDP_TARGET_MEDIA_RENDERER
            )
            
            # Process discovered devices
            for location in discovered_locations:
                await self._add_renderer(location)
            
            self.log(f"Discovery complete. Found {len(self.renderers)} renderer(s)")
            
        except Exception as e:
            logger.error(f"Discovery error: {e}")
            self.log(f"Discovery error: {e}")

    
    async def _add_renderer(self, location: str):
        """
        Add or update a renderer from its description URL.
        
        Args:
            location: URL to device description XML
        """
        try:
            await self._ensure_session()
            
            # Create UPnP device from description
            device: UpnpDevice = await self._factory.async_create_device(location)
            
            udn = device.udn
            if not udn:
                logger.warning(f"Device at {location} has no UDN")
                return
            
            # Extract device information
            parsed_url = urlparse(location)
            ip = parsed_url.hostname
            
            renderer_info = {
                "udn": udn,
                "name": device.name or "Unknown Device",  # UI expects 'name' field
                "friendly_name": device.name or "Unknown Device",
                "location": location,
                "ip": ip,
                "device_type": device.device_type,
                "manufacturer": device.manufacturer,
                "model_name": device.model_name,
                "model_number": device.model_number,
                "serial_number": device.serial_number,
                "firmware_version": getattr(device, "firmware_version", None),
            }
            
            # Find AVTransport and RenderingControl services
            # Use service_id method which is safer than direct dictionary access
            try:
                avt_service = device.service_id("urn:upnp-org:serviceId:AVTransport")
                if avt_service:
                    renderer_info["control_url"] = avt_service.control_url
            except (KeyError, AttributeError):
                # Try alternative lookup
                for service in device.services.values():
                    if "AVTransport" in service.service_type:
                        renderer_info["control_url"] = service.control_url
                        break
            
            try:
                rc_service = device.service_id("urn:upnp-org:serviceId:RenderingControl")
                if rc_service:
                    renderer_info["rendering_control_url"] = rc_service.control_url
            except (KeyError, AttributeError):
                # Try alternative lookup
                for service in device.services.values():
                    if "RenderingControl" in service.service_type:
                        renderer_info["rendering_control_url"] = service.control_url
                        break
            
            # Create DMR device wrapper with event handler
            # For now, we pass None for event_handler (will implement in Phase 2)
            dmr = DmrDevice(device, event_handler=None)
            
            # Check capabilities
            renderer_info["supports_events"] = True  # async-upnp-client supports events
            renderer_info["supports_gapless"] = dmr.has_next_transport_uri
            
            # Store renderer info and DMR device
            self.renderers[udn] = renderer_info
            self.dmr_devices[udn] = dmr
            
            # Persist to database
            await self.save_renderer(renderer_info)
            
            self.log(f"Added renderer: {renderer_info['friendly_name']} ({udn})")
            
        except Exception as e:
            logger.error(f"Error adding renderer from {location}: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            self.log(f"Error adding renderer: {e}")
    
    async def load_persisted_renderers(self):
        """Load previously discovered renderers from database and verify they're still alive."""
        async for db in get_db():
            async with db.execute("SELECT * FROM renderers") as cursor:
                rows = await cursor.fetchall()
                for row in rows:
                    r = dict(row)
                    # Try to verify device is still reachable
                    if await self.verify_device(r):
                        self.renderers[r["udn"]] = r
                        # Try to recreate DMR device
                        if r.get("location"):
                            try:
                                await self._add_renderer(r["location"])
                            except Exception as e:
                                logger.debug(f"Could not recreate DMR for {r['udn']}: {e}")
    
    async def verify_device(self, r: Dict[str, Any]) -> bool:
        """Quick check if device is reachable."""
        if not r.get("location"):
            return False
        
        try:
            await self._ensure_session()
            async with self._session.get(r["location"], timeout=aiohttp.ClientTimeout(total=2)) as resp:
                return resp.status == 200
        except Exception:
            return False
    
    async def save_renderer(self, r: Dict[str, Any]):
        """Persist renderer to database."""
        async for db in get_db():
            await db.execute("""
                INSERT OR REPLACE INTO renderers 
                (udn, friendly_name, location_url, ip, control_url, rendering_control_url, 
                 device_type, manufacturer, model_name, model_number, serial_number, 
                 firmware_version, supports_events, supports_gapless, last_seen)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """, (
                r["udn"], r.get("friendly_name"), r.get("location"), r.get("ip"),
                r.get("control_url"), r.get("rendering_control_url"),
                r.get("device_type"), r.get("manufacturer"), r.get("model_name"),
                r.get("model_number"), r.get("serial_number"), r.get("firmware_version"),
                r.get("supports_events", False), r.get("supports_gapless", False)
            ))
            await db.commit()
    
    async def add_device_by_ip(self, ip: str):
        """
        Manually add a UPnP device by IP address using unicast M-SEARCH and HTTP probing.
        
        Args:
            ip: IP address of the device
        """
        self.log(f"Attempting to add device at {ip}...")
        
        # Try common UPnP ports and paths
        common_urls = [
            f"http://{ip}:49152/description.xml",
            f"http://{ip}:8080/description.xml",
            f"http://{ip}:1400/xml/device_description.xml",  # Sonos
            f"http://{ip}:60053/upnp/dev/uuid/description.xml",  # Rygel
        ]
        
        await self._ensure_session()
        
        for url in common_urls:
            try:
                async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=3)) as resp:
                    if resp.status == 200:
                        await self._add_renderer(url)
                        self.log(f"Successfully added device from {url}")
                        return
            except Exception as e:
                logger.debug(f"Failed to probe {url}: {e}")
        
        self.log(f"Could not find UPnP device at {ip}")
    
    async def scan_subnet(self):
        """Active scan of the local subnet for UPnP devices."""
        self.is_scanning_subnet = True
        self.scan_progress = 0
        self.scan_msg = "Scanning local subnet..."
        
        # Get local subnet
        import ipaddress
        local_network = ipaddress.ip_network(f"{self.local_ip}/24", strict=False)
        
        total_hosts = 254
        scanned = 0
        
        for ip in local_network.hosts():
            if not self.is_scanning_subnet:
                break
            
            ip_str = str(ip)
            scanned += 1
            self.scan_progress = int((scanned / total_hosts) * 100)
            self.scan_msg = f"Scanning {ip_str}..."
            
            await self.add_device_by_ip(ip_str)
        
        self.is_scanning_subnet = False
        self.scan_msg = "Scan complete"
        self.scan_progress = 100
    
    async def get_renderers(self) -> list:
        """Get list of all discovered renderers."""
        return list(self.renderers.values())
    
    async def set_renderer(self, udn: str):
        """Set the active renderer by UDN."""
        if udn in self.renderers:
            self.active_renderer = udn
            self.log(f"Active renderer set to: {self.renderers[udn]['friendly_name']}")
        else:
            raise ValueError(f"Renderer {udn} not found")
    
    async def play_track(self, track_id: int, track_path: str, metadata: Dict[str, Any], username: str = None):
        """
        Play a track on the active renderer.
        
        Args:
            track_id: Track ID from database
            track_path: Path to track file
            metadata: Track metadata (title, artist, album, art_id, duration, mime)
        """
        if not self.active_renderer:
            raise ValueError("No active renderer set")
        
        dmr = self.dmr_devices.get(self.active_renderer)
        if not dmr:
            raise ValueError(f"DMR device not found for {self.active_renderer}")
        
        # Build media URL
        media_url = f"{self.base_url}/api/stream/{track_id}"
        
        # Get MIME type from metadata
        mime_type = metadata.get("mime", "audio/flac")
        
        # Normalize MIME types for UPnP/DLNA compatibility
        # Many devices (including Naim) reject "audio/flac" and require "audio/x-flac"
        mime_type_map = {
            "audio/flac": "audio/x-flac",
            "audio/mp4": "audio/mp4",  # Keep as-is
            "audio/mpeg": "audio/mpeg",  # Keep as-is
        }
        mime_type = mime_type_map.get(mime_type, mime_type)
        
        # Build art URL if available
        art_url = None
        if metadata.get("art_id"):
            art_url = f"{self.base_url}/art/{metadata['art_id']}.jpg"
        
        # Extract metadata fields
        title = metadata.get("title", "Unknown Track")
        artist = metadata.get("artist", "Unknown Artist")
        album = metadata.get("album", "Unknown Album")
        
        # Get renderer info
        renderer_name = self.renderers.get(self.active_renderer, {}).get('friendly_name', 'Unknown')
        renderer_location = self.renderers.get(self.active_renderer, {}).get('location', '')
        renderer_ip = renderer_location.split('//')[1].split(':')[0] if '//' in renderer_location else 'Unknown'
        
        # Build comprehensive log message
        log_parts = [f"Playing: {track_path} : {title} by {artist} ({mime_type}) on {renderer_name}"]
        if renderer_ip and renderer_ip != 'Unknown':
            log_parts.append(f"({renderer_ip})")
        if username:
            log_parts.append(f"requested by {username}")
        
        logger.info(" ".join(log_parts))
        
        # Manually construct DIDL-Lite XML matching the legacy implementation exactly
        # This format has been tested and works with Naim and other renderers
        import html
        title_esc = html.escape(title)
        artist_esc = html.escape(artist)
        album_esc = html.escape(album)
        
        # Note: Legacy uses dc:creator instead of upnp:artist, and includes dlna namespace
        # Build albumArtURI element if artwork is available
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
        
        # Set transport URI with manually constructed metadata
        await dmr.async_set_transport_uri(
            media_url=media_url,
            media_title=title,
            meta_data=didl_lite
        )
        
        # Wait for device to be ready
        await dmr.async_wait_for_can_play(max_wait_time=5)
        
        # Start playback
        try:
            await dmr.async_play()
        except UpnpError as e:
            # Error 701 means "Transition not available" - device is already playing
            if "701" in str(e):
                logger.info(f"Device already playing, ignoring play command")
            else:
                raise
    
    async def pause(self):
        """Pause playback on active renderer."""
        if not self.active_renderer:
            return
        
        dmr = self.dmr_devices.get(self.active_renderer)
        if dmr:
            await dmr.async_pause()
            self.log("Playback paused")
    
    async def resume(self):
        """Resume playback on active renderer."""
        if not self.active_renderer:
            return
        
        dmr = self.dmr_devices.get(self.active_renderer)
        if dmr:
            await dmr.async_play()
            self.log("Playback resumed")
    
    async def set_volume(self, volume_percent: int):
        """
        Set volume on active renderer.
        
        Args:
            volume_percent: Volume level 0-100
        """
        if not self.active_renderer:
            return
        
        dmr = self.dmr_devices.get(self.active_renderer)
        if dmr and dmr.has_volume_level:
            # Convert 0-100 to 0.0-1.0
            volume_level = volume_percent / 100.0
            await dmr.async_set_volume_level(volume_level)
            self.log(f"Volume set to {volume_percent}%")
    
    async def get_position(self, udn: Optional[str] = None) -> tuple:
        """
        Get current playback position and duration.
        
        Args:
            udn: Renderer UDN (uses active if None)
            
        Returns:
            Tuple of (position_seconds, duration_seconds)
        """
        target_udn = udn or self.active_renderer
        if not target_udn:
            return (0, 0)
        
        dmr = self.dmr_devices.get(target_udn)
        if not dmr:
            return (0, 0)
        
        # Update device state from UPnP device
        try:
            await dmr.async_update()
        except Exception as e:
            logger.debug(f"Failed to update DMR state: {e}")
            return (0, 0)
        
        # Get position and duration from DMR device
        position = dmr.media_position
        duration = dmr.media_duration
        
        # Convert to seconds - handle both int and timedelta types
        if isinstance(position, int):
            position_seconds = position
        elif position:
            position_seconds = position.total_seconds()
        else:
            position_seconds = 0
            
        if isinstance(duration, int):
            duration_seconds = duration
        elif duration:
            duration_seconds = duration.total_seconds()
        else:
            duration_seconds = 0
        
        return (position_seconds, duration_seconds)
    
    async def get_transport_info(self, udn: Optional[str] = None) -> str:
        """
        Get current transport state.
        
        Args:
            udn: Renderer UDN (uses active if None)
            
        Returns:
            Transport state string (PLAYING, STOPPED, PAUSED_PLAYBACK, etc.)
        """
        target_udn = udn or self.active_renderer
        if not target_udn:
            return "STOPPED"
        
        dmr = self.dmr_devices.get(target_udn)
        if not dmr:
            return "STOPPED"
        
        # Update device state from UPnP device
        try:
            await dmr.async_update()
        except Exception as e:
            logger.debug(f"Failed to update DMR state: {e}")
            return "STOPPED"
        
        transport_state = dmr.transport_state
        return transport_state.value if transport_state else "STOPPED"
    
    async def seek(self, target_seconds: float):
        """
        Seek to a specific time position.
        
        Args:
            target_seconds: Target position in seconds
        """
        if not self.active_renderer:
            return
        
        dmr = self.dmr_devices.get(self.active_renderer)
        if dmr:
            from datetime import timedelta
            target_time = timedelta(seconds=target_seconds)
            await dmr.async_seek_rel_time(target_time)
            self.log(f"Seeked to {target_seconds}s")
