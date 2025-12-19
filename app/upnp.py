import asyncio
import socket
import logging
import httpx
import xml.etree.ElementTree as ET
from urllib.parse import urlparse
from app.db import get_db

logger = logging.getLogger(__name__)

class UPnPManager:
    _instance = None

    @classmethod
    def get_instance(cls):
        if not cls._instance:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self.renderers = {} # udn -> dict (friendly_name, location, control_url)
        self.active_renderer = None # udn
        self.local_ip = self._get_local_ip()
        self.base_url = None
        self.debug_log = []
        self._bg_task = None

    def start_background_scan(self):
        if not self._bg_task:
            self._bg_task = asyncio.create_task(self._discovery_loop())

    async def _discovery_loop(self):
        while True:
            try:
                self.log("Starting background discovery...")
                await self.discover(timeout=5)
            except Exception as e:
                self.log(f"Background discovery error: {e}")
            
            # Sleep 60s
            await asyncio.sleep(60)

    def log(self, msg):
        import datetime
        ts = datetime.datetime.now().isoformat()
        print(f"[UPnP] {msg}")
        self.debug_log.append(f"[{ts}] {msg}")
        if len(self.debug_log) > 50: self.debug_log.pop(0)

    def _get_local_ip(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('REDACTED_IP', 1))
            IP = s.getsockname()[0]
            s.close()
            return IP
        except Exception:
            return "127.0.0.1"

    async def discover(self, timeout=5):
        """Send M-SEARCH and process responses"""
        MSEARCH = (
            'M-SEARCH * HTTP/1.1\r\n'
            'HOST: 239.255.255.250:1900\r\n'
            'MAN: "ssdp:discover"\r\n'
            'MX: 1\r\n'
            'ST: urn:schemas-upnp-org:service:AVTransport:1\r\n'
            '\r\n'
        ).encode('utf-8')

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(('0.0.0.0', 0)) # Bind to any free port
        
        # Explicit usage probe for user's Naim Atom
        asyncio.create_task(self.add_device_by_ip('REDACTED_IP'))

        # Send
        sock.sendto(MSEARCH, ('239.255.255.250', 1900))
        sock.setblocking(False)

        start = asyncio.get_event_loop().time()
        
        while asyncio.get_event_loop().time() - start < timeout:
            try:
                data, addr = await asyncio.get_event_loop().sock_recv(sock, 1024)
                await self._process_ssdp_packet(data.decode('utf-8', errors='ignore'), addr)
            except Exception:
                await asyncio.sleep(0.1)
        
        sock.close()
        return list(self.renderers.values())

    async def _process_ssdp_packet(self, data, addr):
        lines = data.split('\r\n')
        headers = {}
        for line in lines[1:]:
            if ':' in line:
                key, val = line.split(':', 1)
                headers[key.upper()] = val.strip()
        
        location = headers.get('LOCATION')
        st = headers.get('ST')
        
        if location:
            await self._add_renderer(location)

    async def _add_renderer(self, location):
        self.log(f"Process device location: {location}")
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(location, timeout=5.0) # Increased timeout
                if resp.status_code == 200:
                    xml = resp.text
                    root = ET.fromstring(xml)
                    
                    # Extract Device Info
                    device = root.find('.//{urn:schemas-upnp-org:device-1-0}device')
                    if device is None:
                        device = root.find('.//device') # Try without NS
                    
                    if device:
                        name = device.findtext('{urn:schemas-upnp-org:device-1-0}friendlyName') or device.findtext('friendlyName') or "Unknown"
                        udn = device.findtext('{urn:schemas-upnp-org:device-1-0}UDN') or device.findtext('UDN')
                        self.log(f"Found Device: {name} (UDN: {udn})")
                        
                        # Find AVTransport Control URL
                        services = device.findall('.//{urn:schemas-upnp-org:device-1-0}service')
                        if not services:
                            services = device.findall('.//service')
                            
                        control_url = None
                        for svc in services:
                            svc_type = svc.findtext('{urn:schemas-upnp-org:device-1-0}serviceType') or svc.findtext('serviceType')
                            if 'AVTransport' in (svc_type or ''):
                                control_url = svc.findtext('{urn:schemas-upnp-org:device-1-0}controlURL') or svc.findtext('controlURL')
                                break
                        
                        if udn and control_url:
                            # Normalize Control URL
                            parsed = urlparse(location)
                            base = f"{parsed.scheme}://{parsed.netloc}"
                            if not control_url.startswith('http'):
                                if not control_url.startswith('/'):
                                    control_url = '/' + control_url
                                control_url = base + control_url
                                
                            self.renderers[udn] = {
                                'udn': udn,
                                'name': name,
                                'location': location,
                                'control_url': control_url,
                                'ip': parsed.hostname
                            }
                            self.log(f"Added Renderer: {name} at {control_url}")
                            logger.info(f"Discovered UPnP Renderer: {name} at {control_url}")
                        else:
                            self.log(f"Missing UDN or ControlURL. UDN: {udn}, Ctrl: {control_url}")
                    else:
                        self.log("No device tag found in XML")
                else:
                    self.log(f"HTTP Error {resp.status_code} fetching XML")

        except Exception as e:
            self.log(f"Failed to add renderer from {location}: {e}")
            logger.warning(f"Failed to add renderer from {location}: {e}")

    async def add_device_by_ip(self, ip: str):
        """Manually access UPnP device via Unicast M-SEARCH and HTTP Probing."""
        # 1. Try Unicast M-SEARCH (Standard compliant way for known IP)
        logger.info(f"Probing IP {ip} via Unicast M-SEARCH...")
        try:
             MSEARCH = (
                'M-SEARCH * HTTP/1.1\r\n'
                f'HOST: {ip}:1900\r\n'
                'MAN: "ssdp:discover"\r\n'
                'MX: 1\r\n'
                'ST: urn:schemas-upnp-org:service:AVTransport:1\r\n'
                '\r\n'
             ).encode('utf-8')

             sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
             sock.bind(('0.0.0.0', 0))
             sock.sendto(MSEARCH, (ip, 1900))
             sock.setblocking(False)

             start = asyncio.get_event_loop().time()
             while asyncio.get_event_loop().time() - start < 3:
                 try:
                     # sock_recv returns bytes
                     data = await asyncio.get_event_loop().sock_recv(sock, 2048)
                     # We trust it comes from the IP we sent to (or use sock.recvfrom in executor)
                     # Parse logic
                     await self._process_ssdp_packet(data.decode('utf-8', errors='ignore'), (ip, 1900))
                     sock.close()
                     return True
                 except BlockingIOError:
                     await asyncio.sleep(0.1)
             sock.close()
        except Exception as e:
             logger.warning(f"Unicast M-SEARCH failed: {e}")

        # 2. Fallback to HTTP Port Scan
        logger.info(f"Unicast failed. Probing common ports on {ip}...")
        ports = [8080, 80, 55000, 5000, 5050]
        paths = ['/description.xml', '/device-desc.xml', '/dd.xml']
        
        found = False
        async with httpx.AsyncClient() as client:
            for port in ports:
                for path in paths:
                    url = f"http://{ip}:{port}{path}"
                    try:
                        resp = await client.get(url, timeout=1.0)
                        if resp.status_code == 200 and 'device' in resp.text:
                            logger.info(f"Found Device at {url}")
                            await self._add_renderer(url)
                            found = True
                            break
                    except Exception:
                        pass
                if found: break
        
        return found
                            
    # --- Control Actions ---

    async def get_renderers(self):
        if not self.renderers:
            await self.discover()
        return list(self.renderers.values())

    async def set_renderer(self, udn):
        if udn == 'local':
            self.active_renderer = None
        else:
            if udn not in self.renderers:
                await self.discover()
            if udn in self.renderers:
                self.active_renderer = udn
            else:
                raise ValueError("Renderer not found")

    async def play_track(self, track_id, track_path, metadata):
        """
        Play a track on the active renderer.
        metadata: {title, artist, album, art_id, duration, mime}
        """
        if not self.active_renderer:
            return # Should default to local if active_renderer is None, but handled by caller

        renderer = self.renderers[self.active_renderer]
        control_url = renderer['control_url']

        # Construct Stream URL
        # Use dynamic base_url if available (from API request), else fallback to detected IP
        if self.base_url:
            base = self.base_url
        else:
            base = f"http://{self.local_ip}:8000"

        stream_url = f"{base}/api/stream/{track_id}"
        art_url = f"{base}/art/{metadata.get('art_id')}" if metadata.get('art_id') else ""

        # Construct DIDL
        didl = self._create_didl(stream_url, metadata['mime'], metadata['title'], 
                               metadata['artist'], metadata['album'], art_url)

        # 1. Stop (Optional, safer) - Naim atoms prefer stop before new URI
        try:
            await self._soap_action(control_url, 'Stop', {'InstanceID': 0})
        except Exception as e:
            self.log(f"Stop command failed (ignoring): {e}")

        await asyncio.sleep(0.2)

        # Construct Stream URL
        stream_url = f"{base}/api/stream/{track_id}"
        
        # 2. SetAVTransportURI
        self.log(f"Setting URI: {stream_url}")
        # self.log(f"Meta: {didl}") 
        await self._soap_action(control_url, 'SetAVTransportURI', {
            'InstanceID': 0,
            'CurrentURI': stream_url,
            'CurrentURIMetaData': didl
        })

        await asyncio.sleep(0.2)

        # 3. Play
        await self._soap_action(control_url, 'Play', {
            'InstanceID': 0,
            'Speed': 1
        })

    async def pause(self):
        if self.active_renderer:
            r = self.renderers[self.active_renderer]
            await self._soap_action(r['control_url'], 'Pause', {'InstanceID': 0})

    async def resume(self):
         if self.active_renderer:
            r = self.renderers[self.active_renderer]
            await self._soap_action(r['control_url'], 'Play', {'InstanceID': 0, 'Speed': 1})

    def _create_didl(self, url, mime, title, artist, album, art_url):
        import html
        title = html.escape(title or "Unknown")
        artist = html.escape(artist or "Unknown")
        # Ensure mime is simple
        # Naim might prefer audio/mpeg or audio/x-flac or similar. Use what was passed but ensure protocolInfo format is standard.
        # Fallback to broad match if issues persist.
        
        return f"""
        <DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/" xmlns:dlna="urn:schemas-dlna-org:metadata-1-0/">
            <item id="1" parentID="0" restricted="1">
                <dc:title>{title}</dc:title>
                <dc:creator>{artist}</dc:creator>
                <upnp:class>object.item.audioItem.musicTrack</upnp:class>
                <res protocolInfo="http-get:*:{mime}:*">{url}</res>
            </item>
        </DIDL-Lite>
        """

    async def _soap_action(self, url, action, args):
        self.log(f"SOAP Action: {action} to {url}")
        body = f"""<?xml version="1.0"?>
        <s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
            <s:Body>
                <u:{action} xmlns:u="urn:schemas-upnp-org:service:AVTransport:1">
                    {''.join([f"<{k}>{v}</{k}>" for k, v in args.items()])}
                </u:{action}>
            </s:Body>
        </s:Envelope>
        """
        
        headers = {
            'Content-Type': 'text/xml; charset="utf-8"',
            'SOAPAction': f'"urn:schemas-upnp-org:service:AVTransport:1#{action}"',
            'Connection': 'close'
        }

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, content=body, headers=headers, timeout=10.0) # 10s timeout
                if resp.status_code != 200:
                    self.log(f"SOAP Action {action} FAILED: {resp.status_code} {resp.text}")
                    logger.error(f"SOAP Action {action} failed: {resp.status_code} {resp.text}")
                else:
                    self.log(f"SOAP Action {action} SUCCESS")
        except Exception as e:
            self.log(f"SOAP Action {action} ERROR: {e}")
            raise e
