"""SSRF protection.

Two layers:

1. ``validate_url`` — syntactic checks before any network activity (scheme, credentials, port,
   obviously-internal hostnames).
2. ``SafeNetworkBackend`` — an httpcore network backend used for *every* outbound connection the
   crawler or integrations make. At connect time it resolves the hostname once, rejects the
   connection if *any* resolved address is not a public unicast address, and then connects to the
   validated IP literal. Because the socket connects to the address that was checked, a DNS
   rebinding attack (first answer public, second answer private) cannot redirect the connection.
   TLS still uses the original hostname for SNI and certificate verification.

Redirects are followed manually by the fetcher and every hop goes through both layers again.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import typing
from urllib.parse import urlsplit

import httpcore

from app.core.config import get_settings


class BlockedURLError(Exception):
    """Raised when a URL or resolved address is not allowed."""


_BLOCKED_NETWORKS = [
    ipaddress.ip_network(n)
    for n in (
        "0.0.0.0/8",
        "10.0.0.0/8",
        "100.64.0.0/10",  # carrier-grade NAT (also Alibaba metadata 100.100.100.200)
        "127.0.0.0/8",
        "169.254.0.0/16",  # link-local incl. 169.254.169.254 cloud metadata
        "172.16.0.0/12",
        "192.0.0.0/24",
        "192.0.2.0/24",
        "192.88.99.0/24",
        "192.168.0.0/16",
        "198.18.0.0/15",
        "198.51.100.0/24",
        "203.0.113.0/24",
        "224.0.0.0/4",
        "240.0.0.0/4",
        "255.255.255.255/32",
        "::/128",
        "::1/128",
        "::ffff:0:0/96",  # IPv4-mapped (checked separately after unmapping)
        "64:ff9b::/96",  # NAT64 can reach internal IPv4
        "64:ff9b:1::/48",
        "100::/64",
        "2001::/32",  # Teredo
        "2001:db8::/32",
        "2002::/16",  # 6to4 can embed internal IPv4
        "fc00::/7",  # unique local (incl. AWS fd00:ec2::254 metadata)
        "fe80::/10",
        "ff00::/8",
    )
]

_BLOCKED_HOST_SUFFIXES = (".localhost", ".local", ".internal", ".intranet", ".lan", ".home.arpa", ".corp")
_BLOCKED_HOSTS = {"localhost", "metadata", "metadata.google.internal", "instance-data"}


def is_public_ip(addr: str) -> bool:
    try:
        ip = ipaddress.ip_address(addr.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if any(ip in net for net in _BLOCKED_NETWORKS if net.version == ip.version):
        return False
    return bool(ip.is_global) and not ip.is_multicast and not ip.is_reserved and not ip.is_unspecified


def _dev_allowed(host: str) -> bool:
    s = get_settings()
    return (not s.is_production) and host.lower().strip("[]") in s.dev_allow_hosts


def validate_url(url: str) -> str:
    """Return the normalized URL or raise BlockedURLError."""
    if not isinstance(url, str) or len(url) > 2048:
        raise BlockedURLError("URL is missing or too long.")
    try:
        parts = urlsplit(url.strip())
    except ValueError as exc:
        raise BlockedURLError("URL could not be parsed.") from exc
    if parts.scheme.lower() not in ("http", "https"):
        raise BlockedURLError("Only http and https URLs are allowed.")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise BlockedURLError("URLs with embedded credentials are not allowed.")
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        raise BlockedURLError("URL has no hostname.")
    try:
        port = parts.port
    except ValueError as exc:
        raise BlockedURLError("Invalid port.") from exc
    effective_port = port or (443 if parts.scheme.lower() == "https" else 80)
    dev = _dev_allowed(host)
    if not dev:
        if effective_port not in get_settings().allowed_ports:
            raise BlockedURLError(f"Port {effective_port} is not allowed.")
        if host in _BLOCKED_HOSTS or host.endswith(_BLOCKED_HOST_SUFFIXES):
            raise BlockedURLError("Internal hostnames are not allowed.")
        # Legacy IPv4 shorthands (127.1, 0x7f000001, 2130706433) are interpreted by inet_aton.
        try:
            legacy = socket.inet_ntoa(socket.inet_aton(host))
        except (OSError, ValueError):
            legacy = None
        if legacy is not None and not is_public_ip(legacy):
            raise BlockedURLError("Private, loopback, link-local and reserved addresses are not allowed.")
        # IP literal hosts must be public.
        try:
            ipaddress.ip_address(host.strip("[]"))
            if not is_public_ip(host.strip("[]")):
                raise BlockedURLError("Private, loopback, link-local and reserved addresses are not allowed.")
        except ValueError:
            if "." not in host:
                raise BlockedURLError("Hostname must be a fully-qualified domain name.") from None
    return parts.geturl()


async def resolve_public(host: str, port: int) -> list[str]:
    """Resolve ``host`` and return addresses, raising if any is not public."""
    host = host.strip("[]")
    loop = asyncio.get_running_loop()
    try:
        infos = await asyncio.wait_for(
            loop.getaddrinfo(host, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP), timeout=5
        )
    except (TimeoutError, socket.gaierror) as exc:
        raise BlockedURLError(f"Could not resolve host {host!r}.") from exc
    addrs: list[str] = []
    for family, _, _, _, sockaddr in infos:
        if family not in (socket.AF_INET, socket.AF_INET6):
            continue
        addr = sockaddr[0]
        if addr not in addrs:
            addrs.append(addr)
    if not addrs:
        raise BlockedURLError(f"Host {host!r} has no addresses.")
    if not _dev_allowed(host):
        bad = [a for a in addrs if not is_public_ip(a)]
        if bad:
            raise BlockedURLError(f"Host {host!r} resolves to a non-public address; request blocked.")
    return addrs


class SafeNetworkBackend(httpcore.AsyncNetworkBackend):
    """Validates the destination at connect time and pins the connection to the validated IP."""

    def __init__(self) -> None:
        self._inner = httpcore.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: typing.Iterable[typing.Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        if not _dev_allowed(host) and port not in get_settings().allowed_ports:
            raise BlockedURLError(f"Port {port} is not allowed.")
        addrs = await resolve_public(host, port)
        last_exc: Exception | None = None
        for addr in addrs:
            try:
                return await self._inner.connect_tcp(addr, port, timeout=timeout, local_address=local_address,
                                                     socket_options=socket_options)
            except (httpcore.ConnectError, httpcore.ConnectTimeout, OSError) as exc:
                last_exc = exc
        raise httpcore.ConnectError(f"Unable to connect to {host}: {last_exc}")

    async def connect_unix_socket(self, *args, **kwargs):  # pragma: no cover - never allowed
        raise BlockedURLError("Unix sockets are not allowed.")

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)
