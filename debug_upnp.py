import asyncio
import socket
import logging
import httpx
import xml.etree.ElementTree as ET
from urllib.parse import urlparse

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TARGET_IP = "REDACTED_IP"
TEST_STREAM_URL = "http://www.soundhelix.com/examples/mp3/SoundHelix-Song-1.mp3"

async def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('REDACTED_IP', 1))
        IP = s.getsockname()[0]
        s.close()
        return IP
    except Exception:
        return "127.0.0.1"

async def soap_action(control_url, action, args):
    logger.info(f"Sending SOAP Action: {action} to {control_url}")
    
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
            resp = await client.post(control_url, content=body, headers=headers, timeout=10.0)
            if resp.status_code != 200:
                logger.error(f"SOAP Action {action} FAILED: {resp.status_code}")
                logger.error(resp.text)
                return False
            else:
                logger.info(f"SOAP Action {action} SUCCESS")
                return True
    except Exception as e:
        logger.error(f"SOAP Action {action} ERROR: {e}")
        return False

async def discover_and_play():
    logger.info(f"Attempting to discover {TARGET_IP}...")
    
    # 1. Unicast M-SEARCH
    MSEARCH = (
        'M-SEARCH * HTTP/1.1\r\n'
        f'HOST: {TARGET_IP}:1900\r\n'
        'MAN: "ssdp:discover"\r\n'
        'MX: 1\r\n'
        'ST: urn:schemas-upnp-org:service:AVTransport:1\r\n'
        '\r\n'
    ).encode('utf-8')

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('0.0.0.0', 0))
    sock.sendto(MSEARCH, (TARGET_IP, 1900))
    sock.setblocking(False)

    location = None
    
    try:
        # Wait for response
        start = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start < 5:
            try:
                data = await asyncio.get_event_loop().sock_recv(sock, 2048)
                resp = data.decode('utf-8', errors='ignore')
                if 'AVTransport' in resp:
                    logger.info("Received valid response from device!")
                     # Extract Location
                    import re
                    loc_match = re.search(r'Location: (http://[^\r\n]+)', resp, re.IGNORECASE)
                    if loc_match:
                        location = loc_match.group(1).strip()
                        break
            except BlockingIOError:
                await asyncio.sleep(0.1)
    finally:
        sock.close()

    # Fallback to direct probe if M-Search failed
    if not location:
        logger.info("M-SEARCH failed, trying direct HTTP probe...")
        ports = [8080, 80, 55000, 5000, 8008, 8009]
        xml_paths = ['/description.xml', '/device-desc.xml', '/dd.xml']
        
        async with httpx.AsyncClient() as client:
            for port in ports:
                for path in xml_paths:
                    url = f"http://{TARGET_IP}:{port}{path}"
                    try:
                        resp = await client.get(url, timeout=1.0)
                        if resp.status_code == 200:
                            location = url
                            logger.info(f"Found via direct probe: {location}")
                            break
                    except Exception as e:
                        pass
                if location: break

    if not location:
        logger.error("Could not find device location info.")
        return

    logger.info(f"Reading device description from {location}...")
    
    # Parse XML for ControlURL
    control_url = None
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(location)
            xml = resp.text
            
            # Very basic parsing
            root = ET.fromstring(xml)
            
            # Helper to find with multiple schemes/namespaces or none
            def find_text(node, tag):
                # Try with common NS
                ns = '{urn:schemas-upnp-org:device-1-0}'
                t = node.findtext(f"{ns}{tag}")
                if not t:
                    t = node.findtext(tag)
                return t
                
            services = root.findall('.//{urn:schemas-upnp-org:device-1-0}service')
            if not services:
                services = root.findall('.//service') 
                
            for svc in services:
                stype = find_text(svc, 'serviceType')
                if 'AVTransport' in (stype or ''):
                    control_url = find_text(svc, 'controlURL')
                    logger.info(f"Found AVTransport Control URL: {control_url}")
                    break
            
            if control_url:
                # Fix relative URL
                parsed = urlparse(location)
                base = f"{parsed.scheme}://{parsed.netloc}"
                if not control_url.startswith('http'):
                    if not control_url.startswith('/'):
                        control_url = '/' + control_url
                    control_url = base + control_url
                    
    except Exception as e:
        logger.error(f"Error parsing XML: {e}")
        return

    if not control_url:
        logger.error("Could not find AVTransport Control URL.")
        return

    # PLAYBACK COMMANDS
    logger.info(f"Targeting Control URL: {control_url}")
    
    # Simple DIDL metadata
    didl_lite = f"""
    <DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/" xmlns:dlna="urn:schemas-dlna-org:metadata-1-0/">
        <item id="1" parentID="0" restricted="1">
            <dc:title>Debug Track</dc:title>
            <dc:creator>Debug Artist</dc:creator>
            <upnp:class>object.item.audioItem.musicTrack</upnp:class>
            <res protocolInfo="http-get:*:audio/mpeg:*">{TEST_STREAM_URL}</res>
        </item>
    </DIDL-Lite>
    """
    
    # Use HTML escaping for DIDL in XML
    import html
    didl_escaped = html.escape(didl_lite)

    logging.info(f"Setting URI to: {TEST_STREAM_URL}")
    success = await soap_action(control_url, 'SetAVTransportURI', {
        'InstanceID': 0,
        'CurrentURI': TEST_STREAM_URL,
        'CurrentURIMetaData': didl_escaped
    })
    
    if success:
        logging.info("Starting Playback...")
        await soap_action(control_url, 'Play', {'InstanceID': 0, 'Speed': 1})
    else:
        logging.error("SetAVTransportURI failed.")

if __name__ == "__main__":
    asyncio.run(discover_and_play())
