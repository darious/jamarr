import asyncio
import os
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
        self.debug_log = []
        self.renderers = {} # udn -> dict (friendly_name, location, control_url, rendering_control_url)
        self.active_renderer = None # udn
        self.local_ip = self._get_local_ip()
        self.base_url = None
        self._bg_task = None
        self.is_scanning_subnet = False
        self.scan_progress = 0
        self.scan_msg = ""

    def start_background_scan(self):
        if not self._bg_task:
            self._bg_task = asyncio.create_task(self._discovery_loop())

    async def _discovery_loop(self):
        loop_count = 0
        try:
            while True:
                try:
                    self.log("Starting background discovery...")
                    
                    if loop_count == 0:
                        await self.load_persisted_renderers()
                        
                    await self.discover(timeout=5)
                    
                    # Every 5th loop (approx 5 mins), perform active scan if few renderers found
                    # or just always do it if users have trouble
                    loop_count += 1
                    if loop_count % 5 == 1: 
                        await self.scan_subnet()
                        
                except Exception as e:
                    self.log(f"Background discovery error: {e}")
                
                # Sleep 60s
                await asyncio.sleep(60)
        except asyncio.CancelledError:
            self.log("Background discovery cancelled")
            raise

    def stop_background_scan(self):
        if self._bg_task:
            self._bg_task.cancel()
            self._bg_task = None

    def log(self, msg):
        import datetime
        ts = datetime.datetime.now().isoformat()
        self.debug_log.append(f"[{ts}] {msg}")
        logger.info(f"[UPnP] {msg}")
        if len(self.debug_log) > 50: self.debug_log.pop(0)

    def _get_local_ip(self):
        # 1. Check for manual override via environment variable
        host_ip = os.environ.get('HOST_IP')
        if host_ip:
            self.log(f"Using configured HOST_IP: {host_ip}")
            return host_ip

        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('10.255.255.255', 1))
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
        
        # Bind to 0.0.0.0 to listen for responses on the ephemeral port
        try:
            sock.bind(('0.0.0.0', 0)) 
        except Exception as e:
            self.log(f"Failed to bind discovery socket: {e}")
            return []

        # Send
        try:
            sock.sendto(MSEARCH, ('239.255.255.250', 1900))
        except Exception as e:
             self.log(f"Failed to send M-SEARCH: {e}")
             
        sock.setblocking(False)

        start = asyncio.get_event_loop().time()
        
        while True:
            time_left = timeout - (asyncio.get_event_loop().time() - start)
            if time_left <= 0:
                break
            try:
                data, addr = await asyncio.wait_for(
                    asyncio.get_event_loop().sock_recv(sock, 1024), 
                    timeout=time_left
                )
                await self._process_ssdp_packet(data.decode('utf-8', errors='ignore'), addr)
            except asyncio.TimeoutError:
                break
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
                    if not xml or not xml.strip():
                        # self.log(f"Empty XML from {location}")
                        return
                        
                    root = ET.fromstring(xml)
                    
                    # Extract Device Info
                    device = root.find('.//{urn:schemas-upnp-org:device-1-0}device')
                    if device is None:
                        device = root.find('.//device') # Try without NS
                    
                    if device:
                        name = device.findtext('{urn:schemas-upnp-org:device-1-0}friendlyName') or device.findtext('friendlyName') or "Unknown"
                        udn = device.findtext('{urn:schemas-upnp-org:device-1-0}UDN') or device.findtext('UDN')
                        # self.log(f"Found Device: {name} (UDN: {udn})")
                        
                        # Find AVTransport Control URL
                        services = device.findall('.//{urn:schemas-upnp-org:device-1-0}service')
                        if not services:
                            services = device.findall('.//service')
                            
                        control_url = None
                        rendering_control_url = None
                        
                        for svc in services:
                            svc_type = svc.findtext('{urn:schemas-upnp-org:device-1-0}serviceType') or svc.findtext('serviceType') or ''
                            if 'AVTransport' in svc_type:
                                control_url = svc.findtext('{urn:schemas-upnp-org:device-1-0}controlURL') or svc.findtext('controlURL')
                            elif 'RenderingControl' in svc_type:
                                rendering_control_url = svc.findtext('{urn:schemas-upnp-org:device-1-0}controlURL') or svc.findtext('controlURL')
                        
                        
                        if udn and control_url:
                            # Normalize Control URL
                            parsed = urlparse(location)
                            base = f"{parsed.scheme}://{parsed.netloc}"
                            if not control_url.startswith('http'):
                                if not control_url.startswith('/'):
                                    control_url = '/' + control_url
                                control_url = base + control_url
                                
                            if rendering_control_url:
                                if not rendering_control_url.startswith('http'):
                                    if not rendering_control_url.startswith('/'):
                                        rendering_control_url = '/' + rendering_control_url
                                    rendering_control_url = base + rendering_control_url

                            renderer_data = {
                                'udn': udn,
                                'name': name,
                                'location': location,
                                'control_url': control_url,
                                'rendering_control_url': rendering_control_url,
                                'ip': parsed.hostname
                            }
                            
                            self.renderers[udn] = renderer_data
                            # Persist
                            await self.save_renderer(renderer_data)
                            
                            self.log(f"Added/Updated Renderer: {name} ({parsed.hostname})")
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

    async def load_persisted_renderers(self):
        """Load renderers from DB on startup, check if they are alive, remove dead ones."""
        self.log("Loading persisted renderers...")
        async for db in get_db():
             rows = await db.execute_fetchall("SELECT * FROM renderers")
             for row in rows:
                 r = dict(row)
                 # Map db columns back to internal struct if needed
                 # Schema: friendly_name, udn, location_url, last_seen, control_url, rendering_control_url, ip
                 data = {
                     'udn': r['udn'],
                     'name': r['friendly_name'],
                     'location': r['location_url'],
                     'control_url': r['control_url'],
                     'rendering_control_url': r['rendering_control_url'],
                     'ip': r['ip']
                 }
                 
                 # Optimistic verification
                 is_alive = await self.verify_device(data)
                 if is_alive:
                     self.renderers[data['udn']] = data
                     self.log(f"Restored renderer: {data['name']}")
                 else:
                     self.log(f"Removing dead renderer: {data['name']}")
                     await db.execute("DELETE FROM renderers WHERE udn = ?", (data['udn'],))
                     await db.commit()

    async def verify_device(self, r):
        """Quick check if device is reachable."""
        try:
             async with httpx.AsyncClient() as client:
                 resp = await client.get(r['location'], timeout=2.0)
                 return resp.status_code == 200
        except:
            return False

    async def save_renderer(self, r):
        import time
        async for db in get_db():
            await db.execute("""
                INSERT OR REPLACE INTO renderers 
                (udn, friendly_name, location_url, control_url, rendering_control_url, ip, last_seen)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (r['udn'], r['name'], r['location'], r['control_url'], r['rendering_control_url'], r['ip'], time.time()))
            await db.commit()

    async def add_device_by_ip(self, ip: str):
        """Manually access UPnP device via Unicast M-SEARCH and HTTP Probing."""
        # 1. Try Unicast M-SEARCH (Standard compliant way for known IP)
        # Fast fail (0.5s) to avoid delaying fallback
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
             sock.setblocking(False)
             sock.bind(('0.0.0.0', 0))
             sock.sendto(MSEARCH, (ip, 1900))

             try:
                 data = await asyncio.wait_for(
                    asyncio.get_event_loop().sock_recv(sock, 2048),
                    timeout=1.5 # Increased from 0.3s for slower devices like Naim
                 )
                 await self._process_ssdp_packet(data.decode('utf-8', errors='ignore'), (ip, 1900))
                 sock.close()
                 return True
             except:
                 pass
             sock.close()
        except:
             pass

        # 2. Fallback to HTTP Port Scan (Parallelized)
        ports = [8080, 80, 55000, 5000, 5050, 1400, 54380]
        paths = ['/description.xml', '/device-desc.xml', '/dd.xml', '/xml/device_description.xml', '/MediaRenderer_TA-AN1000.xml', '/dmr.xml']
        
        # Helper to check a specific url
        async def check_url(client, url):
            try:
                resp = await client.get(url, timeout=1.0)
                if resp.status_code == 200 and ('device' in resp.text or 'root' in resp.text):
                     return url
            except:
                pass
            return None

        # Gather all probes
        probe_tasks = []
        async with httpx.AsyncClient() as client:
            for port in ports:
                # Optimization: Try to connect to port first? 
                # Actually, blindly firing 42 requests in parallel is fine for async, 
                # as long as we don't wait sequentially.
                for path in paths:
                    url = f"http://{ip}:{port}{path}"
                    probe_tasks.append(check_url(client, url))
            
            # Run all probes for this IP in parallel
            results = await asyncio.gather(*probe_tasks)
            
            for url in results:
                if url:
                    logger.info(f"Found Device at {url}")
                    await self._add_renderer(url)
                    return True
        
        return False
    
    async def scan_subnet(self):
        """Active scan of the local subnet and common home subnets."""
        if self.is_scanning_subnet:
            return

        self.is_scanning_subnet = True
        self.scan_progress = 0
        self.scan_msg = "Starting active scan..."
        self.log("Starting active subnet scan...")
        
        try:
            subnets = set()
            local_ip = self.local_ip
            if local_ip and local_ip != '127.0.0.1':
                subnets.add('.'.join(local_ip.split('.')[:-1]))
            subnets.add('192.168.0')
            subnets.add('192.168.1')
            
            total_ips = len(subnets) * 254
            processed_ips = 0

            tasks = []
            chunk_size = 10 
            
            for idx, subnet in enumerate(subnets):
                self.log(f"Scanning subnet {subnet}.x ...")
                
                for i in range(1, 255):
                    processed_ips += 1
                    # Update progress every 2 IPs
                    if i % 2 == 0:
                        pct = int((processed_ips / total_ips) * 100)
                        self.scan_progress = pct
                        self.scan_msg = f"Scanning {subnet}.{i} ({pct}%)"

                    target_ip = f"{subnet}.{i}"
                    if target_ip == local_ip: continue
                    
                    tasks.append(self.add_device_by_ip(target_ip))
                    
                    if len(tasks) >= chunk_size:
                        await asyncio.gather(*tasks)
                        tasks = []
                        await asyncio.sleep(0.01)
                
                if tasks:
                    await asyncio.gather(*tasks)
                    tasks = []
                
            self.log("Active subnet scan completed.")
            self.scan_progress = 100
            self.scan_msg = "Scan complete."
        finally:
            self.is_scanning_subnet = False
            self.scan_progress = 0
            self.scan_msg = ""
                            
    # --- Control Actions ---

    async def get_renderers(self):
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
            base = f"http://{self.local_ip}:8111"

        stream_url = f"{base}/api/stream/{track_id}"
        # Disable album art in DIDL; some renderers reject external art URIs (e.g., Naim 701 errors)
        art_url = None

        # Construct DIDL
        didl = self._create_didl(stream_url, metadata['mime'], metadata['title'], 
                               metadata['artist'], metadata['album'], art_url)
        if os.environ.get("UPNP_LOG_DIDL"):
            logger.info(f"DIDL sent:\n{didl}")

        # 1. Stop (Optional, safer) - Naim atoms prefer stop before new URI
        ok, resp = await self._soap_action(control_url, 'Stop', {'InstanceID': 0})
        if not ok:
            self.log(f"Stop command failed (continuing): {resp}")

        await asyncio.sleep(0.2)

        # Construct Stream URL
        stream_url = f"{base}/api/stream/{track_id}"
        
        # 2. SetAVTransportURI
        self.log(f"Setting URI: {stream_url}")
        # self.log(f"Meta: {didl}") 
        ok, resp = await self._soap_action(control_url, 'SetAVTransportURI', {
            'InstanceID': 0,
            'CurrentURI': stream_url,
            'CurrentURIMetaData': didl
        })
        if not ok:
            self.log(f"SetAVTransportURI failed, aborting Play: {resp}")
            return

        await asyncio.sleep(0.6)  # give renderer a moment to ingest metadata

        # 3. Play
        ok, resp = await self._soap_action(control_url, 'Play', {
            'InstanceID': 0,
            'Speed': 1
        })
        if not ok:
            self.log(f"Play failed: {resp}")

    async def pause(self):
        if self.active_renderer:
            r = self.renderers[self.active_renderer]
            await self._soap_action(r['control_url'], 'Pause', {'InstanceID': 0})

    async def resume(self):
         if self.active_renderer:
            r = self.renderers[self.active_renderer]
            await self._soap_action(r['control_url'], 'Play', {'InstanceID': 0, 'Speed': 1})

    async def set_volume(self, volume_percent: int):
        if self.active_renderer:
            r = self.renderers[self.active_renderer]
            rc_url = r.get('rendering_control_url')
            if rc_url:
                await self._soap_action(rc_url, 'SetVolume', {
                    'InstanceID': 0,
                    'Channel': 'Master',
                    'DesiredVolume': volume_percent
                })
            else:
                self.log("No RenderingControl URL for active renderer")

    def _create_didl(self, url, mime, title, artist, album, art_url=None):
        import html
        title = html.escape(title or "Unknown")
        artist = html.escape(artist or "Unknown")
        album = html.escape(album or "Unknown")
        # Ensure mime is simple
        # Naim might prefer audio/mpeg or audio/x-flac or similar. Use what was passed but ensure protocolInfo format is standard.
        # Fallback to broad match if issues persist.
        
        return f"""
        <DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/" xmlns:dlna="urn:schemas-dlna-org:metadata-1-0/">
            <item id="1" parentID="0" restricted="1">
                <dc:title>{title}</dc:title>
                <dc:creator>{artist}</dc:creator>
                <upnp:album>{album}</upnp:album>
                <upnp:class>object.item.audioItem.musicTrack</upnp:class>
                <res protocolInfo="http-get:*:{mime}:*">{url}</res>
            </item>
        </DIDL-Lite>
        """

    async def _soap_action(self, url, action, args):
        """Send SOAP action and return (ok, response_text)."""
        self.log(f"SOAP Action: {action} to {url}")
        # Helper to escape values
        import html
        def escape_val(val):
            return html.escape(str(val))

        body = f"""<?xml version="1.0"?>
        <s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
            <s:Body>
                <u:{action} xmlns:u="urn:schemas-upnp-org:service:AVTransport:1" xmlns:r="urn:schemas-upnp-org:service:RenderingControl:1">
                    {''.join([f"<{k}>{escape_val(v)}</{k}>" for k, v in args.items()])}
                </u:{action}>
            </s:Body>
        </s:Envelope>
        """
        
        # Log the full request body for debugging
        # logger.debug(f"SOAP Request Body ({action}):\n{body}")

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
                    return False, resp.text
                else:
                    self.log(f"SOAP Action {action} SUCCESS")
                    logger.debug(f"SOAP Action {action} Response:\n{resp.text}")
                    return True, resp.text
        except Exception as e:
            self.log(f"SOAP Action {action} ERROR: {e}")
            logger.exception(f"SOAP Action {action} Exception")
            return False, str(e)

    def _parse_time(self, time_str):
        if not time_str or time_str == 'NOT_IMPLEMENTED':
            return 0
        try:
            parts = time_str.split(':')
            if len(parts) == 3:
                h, m, s = map(float, parts)
                return h * 3600 + m * 60 + s
        except:
            pass
        return 0

    async def get_position(self, udn=None):
        """Get current position and duration from active renderer or specified udn."""
        target_udn = udn or self.active_renderer
        if not target_udn or target_udn not in self.renderers:
            return 0, 0
        
        r = self.renderers[target_udn]
        url = r['control_url']
        
        try:
            # GetPositionInfo
            action = "GetPositionInfo"
            body = f"""<?xml version="1.0"?>
            <s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
                <s:Body>
                    <u:{action} xmlns:u="urn:schemas-upnp-org:service:AVTransport:1">
                        <InstanceID>0</InstanceID>
                    </u:{action}>
                </s:Body>
            </s:Envelope>
            """
            
            headers = {
                'Content-Type': 'text/xml; charset="utf-8"',
                'SOAPAction': f'"urn:schemas-upnp-org:service:AVTransport:1#{action}"'
            }
            
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, content=body, headers=headers, timeout=2.0)
                if resp.status_code == 200:
                    xml = resp.text
                    # Parse RelTime and TrackDuration
                    # <RelTime>00:00:23</RelTime>
                    # <TrackDuration>00:03:45</TrackDuration>
                    
                    # Simple parsing
                    rel_time = 0
                    duration = 0
                    
                    import re
                    rel_match = re.search(r'<RelTime>(.*?)</RelTime>', xml)
                    dur_match = re.search(r'<TrackDuration>(.*?)</TrackDuration>', xml)
                    
                    if rel_match:
                        rel_time = self._parse_time(rel_match.group(1))
                    if dur_match:
                        duration = self._parse_time(dur_match.group(1))
                        
                    return rel_time, duration
        except Exception as e:
            self.log(f"GetPositionInfo failed: {e}")
            
        return 0, 0

    async def get_transport_info(self, udn=None):
        """Get CurrentTransportState (PLAYING, STOPPED, PAUSED_PLAYBACK, etc)."""
        target_udn = udn or self.active_renderer
        if not target_udn or target_udn not in self.renderers:
            return "STOPPED"
        
        r = self.renderers[target_udn]
        url = r['control_url']
        
        try:
            action = "GetTransportInfo"
            body = f"""<?xml version="1.0"?>
            <s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
                <s:Body>
                    <u:{action} xmlns:u="urn:schemas-upnp-org:service:AVTransport:1">
                        <InstanceID>0</InstanceID>
                    </u:{action}>
                </s:Body>
            </s:Envelope>
            """
            
            headers = {
                'Content-Type': 'text/xml; charset="utf-8"',
                'SOAPAction': f'"urn:schemas-upnp-org:service:AVTransport:1#{action}"'
            }
            
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, content=body, headers=headers, timeout=2.0)
                if resp.status_code == 200:
                    xml = resp.text
                    import re
                    match = re.search(r'<CurrentTransportState>(.*?)</CurrentTransportState>', xml)
                    if match:
                        return match.group(1)
        except Exception as e:
            self.log(f"GetTransportInfo failed: {e}")
            
        return "UNKNOWN"

    async def seek(self, target_seconds: float):
        """Seek to a specific time (REL_TIME)."""
        if not self.active_renderer:
            return

        r = self.renderers[self.active_renderer]
        control_url = r['control_url']
        
        # Format as H:MM:SS
        m, s = divmod(int(target_seconds), 60)
        h, m = divmod(m, 60)
        target = f"{h}:{m:02d}:{s:02d}"
        
        self.log(f"Seeking to {target}")
        
        await self._soap_action(control_url, 'Seek', {
            'InstanceID': 0,
            'Unit': 'REL_TIME',
            'Target': target
        })
