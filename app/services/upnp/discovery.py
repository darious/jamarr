from typing import Dict, Any, Optional
import asyncio
import logging
import aiohttp
from urllib.parse import urlparse
from async_upnp_client.search import async_search
from async_upnp_client.client import UpnpDevice
from async_upnp_client.profiles.dlna import DmrDevice
from async_upnp_client.utils import CaseInsensitiveDict

from app.db import get_db
from app.services.upnp.utils import select_renderer_icon

logger = logging.getLogger(__name__)

SSDP_TARGET_MEDIA_RENDERER = "urn:schemas-upnp-org:device:MediaRenderer:1"

class UPnPDiscovery:
    def __init__(self, manager):
        self.manager = manager
        self._running = False
        self._discovery_task: Optional[asyncio.Task] = None
        self.is_scanning_subnet = False
        self.scan_msg = ""
        self.scan_progress = 0

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
        self.manager.log("Stopped background UPnP discovery")

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
        """
        await self.manager._ensure_session()
        self.manager.log(f"Starting UPnP discovery (timeout={timeout}s)...")
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
                search_target=SSDP_TARGET_MEDIA_RENDERER,
            )

            # Process discovered devices
            for location in discovered_locations:
                await self._add_renderer(location)

            self.manager.log(f"Discovery complete. Found {len(self.manager.renderers)} renderer(s)")

        except Exception as e:
            logger.error(f"Discovery error: {e}")
            self.manager.log(f"Discovery error: {e}")

    async def _add_renderer(self, location: str):
        """
        Add or update a renderer from its description URL.
        """
        try:
            await self.manager._ensure_session()
            factory = self.manager._factory

            # Create UPnP device from description
            device: UpnpDevice = await factory.async_create_device(location)

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
            try:
                avt_service = device.service_id("urn:upnp-org:serviceId:AVTransport")
                if avt_service:
                    renderer_info["control_url"] = avt_service.control_url
            except (KeyError, AttributeError):
                for service in device.services.values():
                    if "AVTransport" in service.service_type:
                        renderer_info["control_url"] = service.control_url
                        break

            try:
                rc_service = device.service_id("urn:upnp-org:serviceId:RenderingControl")
                if rc_service:
                    renderer_info["rendering_control_url"] = rc_service.control_url
            except (KeyError, AttributeError):
                for service in device.services.values():
                    if "RenderingControl" in service.service_type:
                        renderer_info["rendering_control_url"] = service.control_url
                        break

            # Create DMR device wrapper
            dmr = DmrDevice(device, event_handler=None)

            # Check capabilities
            renderer_info["supports_events"] = True
            renderer_info["supports_gapless"] = dmr.has_next_transport_uri

            # Query supported MIME types (call manager helper or import?)
            # Since get_supported_protocols was on manager and used dmr,
            # we can setup dmr on manager first then call it.
            
            # Update manager state
            self.manager.renderers[udn] = renderer_info
            self.manager.dmr_devices[udn] = dmr
            
            # Now we can query protocols using the manager which has the DMR
            supported_mimes = await self.manager.get_supported_protocols(udn)

            if supported_mimes:
                renderer_info["supported_mime_types"] = ",".join(sorted(supported_mimes))
                logger.debug(f"  Supports {len(supported_mimes)} MIME types")
            else:
                # Check DB for existing
                async for db in get_db():
                    row = await db.fetchrow(
                        "SELECT supported_mime_types FROM renderer WHERE udn = $1", udn
                    )
                    if row and row["supported_mime_types"]:
                        renderer_info["supported_mime_types"] = row["supported_mime_types"]
                        logger.debug("  Preserving existing MIME types from database")
                    else:
                        renderer_info["supported_mime_types"] = ""

            # Icons
            icon = await select_renderer_icon(self.manager._session, location)
            if icon:
                renderer_info["icon_url"] = icon.get("url")
                renderer_info["icon_mime"] = icon.get("mimetype")
                renderer_info["icon_width"] = icon.get("width")
                renderer_info["icon_height"] = icon.get("height")
            
            if "icon_url" in renderer_info:
                renderer_info["original_icon_url"] = renderer_info["icon_url"]

            # Save to DB
            await self.manager.save_renderer(renderer_info)

            # Cache icon
            has_cached = await self.manager._cache_renderer_icon(udn, icon)
            if has_cached:
                renderer_info["icon_url"] = f"/art/renderer/{udn}"
                self.manager.renderers[udn] = renderer_info

            self.manager.log(f"Added renderer: {renderer_info['friendly_name']} ({udn})")

        except Exception as e:
            logger.error(f"Error adding renderer from {location}: {e}")
            self.manager.log(f"Error adding renderer: {e}")

    async def load_persisted_renderers(self):
        """Load previously discovered renderers from database."""
        async for db in get_db():
            rows = await db.fetch("""
                SELECT r.*, im.artwork_id as has_local_icon
                FROM renderer r
                LEFT JOIN image_map im ON im.entity_type = 'renderer' AND im.entity_id = r.udn AND im.image_type = 'icon'
            """)
            for row in rows:
                r = dict(row)
                has_local = r.pop("has_local_icon", None)
                r["original_icon_url"] = r.get("icon_url")
                if has_local:
                    r["icon_url"] = f"/art/renderer/{r['udn']}"

                location = r.get("location") or r.get("location_url")
                if location:
                    r["location"] = location
                
                if await self.verify_device(r):
                    self.manager.renderers[r["udn"]] = r
                    if r.get("location"):
                        try:
                            await self._add_renderer(r["location"])
                        except Exception as e:
                            logger.debug(f"Could not recreate DMR for {r['udn']}: {e}")

    async def verify_device(self, r: Dict[str, Any]) -> bool:
        """Quick check if device is reachable."""
        location = r.get("location") or r.get("location_url")
        if not location:
            return False

        try:
            await self.manager._ensure_session()
            async with self.manager._session.get(
                location, timeout=aiohttp.ClientTimeout(total=2)
            ) as resp:
                return resp.status == 200
        except Exception:
            return False

    async def add_device_by_ip(self, ip: str):
        """Manually add UPnP device by IP."""
        self.manager.log(f"Attempting to add device at {ip}...")
        common_urls = [
            f"http://{ip}:49152/description.xml",
            f"http://{ip}:8080/description.xml",
            f"http://{ip}:1400/xml/device_description.xml",
            f"http://{ip}:60053/upnp/dev/uuid/description.xml",
        ]

        await self.manager._ensure_session()
        for url in common_urls:
            try:
                async with self.manager._session.get(
                    url, timeout=aiohttp.ClientTimeout(total=3)
                ) as resp:
                    if resp.status == 200:
                        await self._add_renderer(url)
                        self.manager.log(f"Successfully added device from {url}")
                        return
            except Exception as e:
                logger.debug(f"Failed to probe {url}: {e}")
        self.manager.log(f"Could not find UPnP device at {ip}")

    async def scan_subnet(self):
        """Active scan of the local subnet for UPnP devices."""
        self.is_scanning_subnet = True
        self.scan_progress = 0
        self.scan_msg = "Scanning local subnet..."
        import ipaddress

        try:
            local_network = ipaddress.ip_network(f"{self.manager.local_ip}/24", strict=False)
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
        except Exception as e:
            logger.error(f"Subnet scan error: {e}")
            self.scan_msg = f"Scan error: {e}"
        finally:
            self.is_scanning_subnet = False
            self.scan_msg = "Scan complete"
            self.scan_progress = 100
