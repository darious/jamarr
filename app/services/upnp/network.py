"""Local-network helpers for UPnP discovery: source address and subnet."""

from __future__ import annotations

import ipaddress
import logging
import socket

logger = logging.getLogger(__name__)

# Never sweep more than a /22 (1022 hosts): anything wider is almost certainly
# a container bridge or a mis-detected interface, not a home LAN.
MAX_SCAN_PREFIX = 22
DEFAULT_PREFIX = 24


def default_route_ip() -> str:
    """The IPv4 address the kernel would use for outbound traffic."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        finally:
            s.close()
    except Exception:
        return "127.0.0.1"


def interface_prefix(ip: str) -> int | None:
    """Prefix length of the local interface holding ``ip``, if it can be found."""
    try:
        import ifaddr
    except ImportError:  # pragma: no cover - ifaddr ships with zeroconf
        return None
    try:
        for adapter in ifaddr.get_adapters():
            for addr in adapter.ips:
                if isinstance(addr.ip, str) and addr.ip == ip:
                    return int(addr.network_prefix)
    except Exception as exc:
        logger.debug("Interface lookup failed: %s", exc)
    return None


def interface_name(ip: str) -> str | None:
    try:
        import ifaddr

        for adapter in ifaddr.get_adapters():
            for addr in adapter.ips:
                if isinstance(addr.ip, str) and addr.ip == ip:
                    return adapter.nice_name or adapter.name
    except Exception:
        pass
    return None


def scan_network(ip: str, prefix: int | None = None) -> tuple[ipaddress.IPv4Network, bool]:
    """The network to sweep for ``ip``: the real interface subnet, clipped.

    Returns ``(network, clipped)``. Falls back to /24 when the interface
    prefix is unknown; narrows anything wider than /22 to the /22 that
    contains ``ip``.
    """
    if prefix is None:
        prefix = interface_prefix(ip)
    if prefix is None:
        prefix = DEFAULT_PREFIX
    clipped = False
    if prefix < MAX_SCAN_PREFIX:
        prefix = MAX_SCAN_PREFIX
        clipped = True
    return ipaddress.ip_network(f"{ip}/{prefix}", strict=False), clipped
