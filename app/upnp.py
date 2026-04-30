"""
UPnP Manager Module
Delegates functionality to specialized services in app/services/upnp/
"""
import logging
import asyncio
import aiohttp
from typing import Dict, Any, Optional, List

from async_upnp_client.client_factory import UpnpFactory
from async_upnp_client.profiles.dlna import DmrDevice
from async_upnp_client.aiohttp import AiohttpSessionRequester

from app.services.upnp.utils import (
    select_renderer_icon,
    fetch_device_icons
)
from app.services.upnp.discovery import UPnPDiscovery
from app.services.upnp.device import UPnPDeviceControl

logger = logging.getLogger(__name__)

# Search target for MediaRenderer devices
SSDP_TARGET_MEDIA_RENDERER = "urn:schemas-upnp-org:device:MediaRenderer:1"

class UPnPManager:
    """
    UPnP/DLNA Media Renderer Manager using async-upnp-client library.
    Acts as a facade/coordinator for Discovery and Device Control services.
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

        # HTTP session for library
        self._session: Optional[aiohttp.ClientSession] = None
        self._requester: Optional[AiohttpSessionRequester] = None
        self._factory: Optional[UpnpFactory] = None

        # Delegated Services
        self.discovery = UPnPDiscovery(self)
        self.control = UPnPDeviceControl(self)

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

    # --- Delegate to Utils (Public API) ---
    async def _fetch_device_icons(self, location: str) -> List[Dict[str, Any]]:
        await self._ensure_session()
        return await fetch_device_icons(self._session, location)

    async def _select_renderer_icon(self, location: str) -> Optional[Dict[str, Any]]:
        await self._ensure_session()
        return await select_renderer_icon(self._session, location)

    async def _cache_renderer_icon(self, udn: str, icon: Optional[Dict[str, Any]]) -> bool:
        # Kept internal as it interacts with manager-specific DB logic possibly? 
        # But actually let's implement it here as it was, or move to discovery if strictly discovery related.
        # It's better here or in a separate persistence service. 
        # For now, keep logic here to avoid circular imports or complex dependency injection 
        # if it wasn't moved.
        if not udn or not icon or not icon.get("url"):
            return False
        from app.scanner.artwork import download_and_save_artwork, upsert_artwork_record, upsert_image_mapping
        from app.db import get_db

        icon_url = icon["url"]
        async for db in get_db():
            row = await db.fetchrow(
                """
                SELECT r.icon_url, im.artwork_id
                FROM renderer r
                LEFT JOIN image_map im
                  ON im.entity_type = 'renderer'
                  AND im.entity_id = $1
                  AND im.image_type = 'icon'
                WHERE r.udn = $1
                """,
                udn,
            )
            if row and row["icon_url"] == icon_url and row["artwork_id"]:
                return True

            downloaded = await download_and_save_artwork(
                icon_url, art_type="renderer_icon"
            )
            if not downloaded:
                return False
            artwork_id = await upsert_artwork_record(
                db,
                downloaded["sha1"],
                downloaded["meta"],
                source="upnp",
                source_url=downloaded["source_url"],
            )
            await upsert_image_mapping(db, artwork_id, "renderer", udn, "icon")
            return True

    # --- Delegate to Discovery Service ---

    def start_background_scan(self):
        self.discovery.start_background_scan()

    async def stop_background_scan(self):
        await self.discovery.stop_background_scan()
        # Cleanup HTTP session part kept here as it owns the session
        if self._session:
            try:
                await asyncio.wait_for(self._session.close(), timeout=2.0)
            except Exception as e:
                logger.debug(f"Error closing UPnP session: {e}")
            self._session = None
            self._requester = None
            self._factory = None
        self.log("Stopped background UPnP discovery")

    async def discover(self, timeout=5):
        await self.discovery.discover(timeout)

    async def _add_renderer(self, location: str):
        # Exposed for testing/re-add but mainly internal
        await self.discovery._add_renderer(location)

    async def load_persisted_renderers(self):
        await self.discovery.load_persisted_renderers()

    async def verify_device(self, r: Dict[str, Any]) -> bool:
        return await self.discovery.verify_device(r)

    async def save_renderer(self, r: Dict[str, Any]):
        # This one writes to DB, kept here or moved?
        # It was on Manager. Let's keep it here or move to a persistence module.
        # Discovery uses it. Let's keep it here to allow Discovery to call back.
        from app.db import get_db
        async for db in get_db():
            await db.execute(
                """
                INSERT INTO renderer 
                (udn, kind, native_id, renderer_id, friendly_name, location_url, ip, control_url, rendering_control_url,
                 device_type, manufacturer, model_name, model_number, serial_number, 
                 firmware_version, supports_events, supports_gapless, supported_mime_types,
                 icon_url, icon_mime, icon_width, icon_height, last_discovered_by, available, enabled_by_default, last_seen_at)
                VALUES ($1, 'upnp', $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, $20, 'server', TRUE, TRUE, NOW())
                ON CONFLICT (udn) DO UPDATE SET
                    kind = 'upnp',
                    native_id = EXCLUDED.native_id,
                    renderer_id = EXCLUDED.renderer_id,
                    friendly_name = EXCLUDED.friendly_name,
                    location_url = EXCLUDED.location_url,
                    ip = EXCLUDED.ip,
                    control_url = EXCLUDED.control_url,
                    rendering_control_url = EXCLUDED.rendering_control_url,
                    device_type = EXCLUDED.device_type,
                    manufacturer = EXCLUDED.manufacturer,
                    model_name = EXCLUDED.model_name,
                    model_number = EXCLUDED.model_number,
                    serial_number = EXCLUDED.serial_number,
                    firmware_version = EXCLUDED.firmware_version,
                    supports_events = EXCLUDED.supports_events,
                    supports_gapless = EXCLUDED.supports_gapless,
                    supported_mime_types = EXCLUDED.supported_mime_types,
                    icon_url = EXCLUDED.icon_url,
                    icon_mime = EXCLUDED.icon_mime,
                    icon_width = EXCLUDED.icon_width,
                    icon_height = EXCLUDED.icon_height,
                    last_discovered_by = EXCLUDED.last_discovered_by,
                    available = TRUE,
                    enabled_by_default = COALESCE(renderer.enabled_by_default, TRUE),
                    last_seen_at = NOW()
            """,
                r["udn"],
                f"upnp:{r['udn']}",
                r.get("friendly_name"),
                r.get("location"),
                r.get("ip"),
                r.get("control_url"),
                r.get("rendering_control_url"),
                r.get("device_type"),
                r.get("manufacturer"),
                r.get("model_name"),
                r.get("model_number"),
                r.get("serial_number"),
                r.get("firmware_version"),
                r.get("supports_events", False),
                r.get("supports_gapless", False),
                r.get("supported_mime_types", ""),
                r.get("original_icon_url") or r.get("icon_url"),
                r.get("icon_mime"),
                r.get("icon_width"),
                r.get("icon_height"),
            )

    async def add_device_by_ip(self, ip: str):
        await self.discovery.add_device_by_ip(ip)

    async def scan_subnet(self):
        await self.discovery.scan_subnet()
    
    @property
    def is_scanning_subnet(self):
        return self.discovery.is_scanning_subnet
    
    @property
    def scan_msg(self):
        return self.discovery.scan_msg
    
    @property
    def scan_progress(self):
        return self.discovery.scan_progress

    # --- Delegate to Device Control Service ---

    async def get_renderers(self) -> list:
        # Simple local access
        return list(self.renderers.values())

    async def set_renderer(self, udn: str):
        # Local state update
        if udn in self.renderers:
            self.active_renderer = udn
            self.log(f"Active renderer set to: {self.renderers[udn]['friendly_name']}")
        else:
            raise ValueError(f"Renderer {udn} not found")

    async def get_supported_protocols(self, udn: str) -> set:
        return await self.control.get_supported_protocols(udn)

    async def play_track(self, track_id: int, track_path: str, metadata: Dict[str, Any], username: str = None):
        return await self.control.play_track(track_id, track_path, metadata, username)

    async def pause(self):
        return await self.control.pause()

    async def resume(self):
        return await self.control.resume()

    async def seek(self, target_seconds: float):
        return await self.control.seek(target_seconds)

    async def set_volume(self, volume: int) -> None:
        return await self.control.set_volume(volume)

    async def get_position(self, udn: Optional[str] = None):
        return await self.control.get_position(udn)

    async def get_transport_info(self, udn: Optional[str] = None):
        return await self.control.get_transport_info(udn)
