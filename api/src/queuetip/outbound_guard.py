"""SSRF guard for outbound requests to user-supplied URLs.

QueueTip fetches URLs that signed-in users control (Subsonic `server_url`,
Apple Music links). Without a guard, the internet-facing process can be steered
at this stack's own services (the unauthenticated admin API, Postgres, Valkey)
or at cloud metadata endpoints.

Policy: private LAN ranges (RFC1918) are deliberately ALLOWED because
self-hosted Navidrome servers commonly live on the LAN. What is blocked:

  * loopback, unspecified, link-local (incl. 169.254.169.254), multicast and
    reserved addresses;
  * hostnames that are this stack's Docker service names;
  * any address inside a network this container is itself attached to
    (the Docker bridge), detected at runtime.

Every resolved address of a host must pass. Callers must invoke
`validate_outbound_url` immediately before each request so a DNS answer that
changes between save time and request time (rebinding) is re-checked.
"""

from __future__ import annotations

import ipaddress
import logging
import os
import socket
from typing import Iterable, Union

import httpx

logger = logging.getLogger(__name__)

IPNetwork = Union[ipaddress.IPv4Network, ipaddress.IPv6Network]
IPAddress = Union[ipaddress.IPv4Address, ipaddress.IPv6Address]

# Env override for tests / unusual topologies. When set (comma-separated CIDRs)
# it REPLACES the auto-detected container networks.
BLOCKED_NETWORKS_ENV = "QUEUETIP_OUTBOUND_BLOCKED_NETWORKS"

BLOCKED_HOSTNAMES = frozenset(
    {
        "localhost",
        "web",
        "worker",
        "beat",
        "postgres",
        "valkey",
        "frontend",
        "frontend-dev",
        "queuetip",
        "queuetip-frontend",
    }
)

_ALWAYS_BLOCKED_NETWORKS: tuple[IPNetwork, ...] = (
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("fd00:ec2::/32"),  # AWS IPv6 metadata
)


class UnsafeURLError(ValueError):
    """The URL points somewhere outbound requests must not go.

    The message is generic and safe to show to end users.
    """


def _container_networks() -> list[IPNetwork]:
    """Networks of this container's own interfaces (e.g. the Docker bridge)."""
    override = os.environ.get(BLOCKED_NETWORKS_ENV)
    if override is not None:
        networks: list[IPNetwork] = []
        for entry in override.split(","):
            entry = entry.strip()
            if entry:
                networks.append(ipaddress.ip_network(entry, strict=False))
        return networks

    try:
        import psutil  # pylint: disable=import-outside-toplevel

        interfaces = psutil.net_if_addrs()
    except Exception:  # pylint: disable=broad-except
        logger.warning("Could not enumerate interfaces for the SSRF guard")
        return []

    networks = []
    for addrs in interfaces.values():
        for snic in addrs:
            if snic.family not in (socket.AF_INET, socket.AF_INET6):
                continue
            if not snic.address or not snic.netmask:
                continue
            try:
                ip = ipaddress.ip_address(snic.address.split("%")[0])
                prefix = bin(int(ipaddress.ip_address(snic.netmask))).count("1")
                networks.append(ipaddress.ip_network(f"{ip}/{prefix}", strict=False))
            except ValueError:
                continue
    return networks


def _resolve_host(host: str) -> list[str]:
    """Resolve `host` to every address it maps to (separate for test patching)."""
    infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return sorted({str(info[4][0]) for info in infos})


def _is_blocked_ip(ip: IPAddress, networks: Iterable[IPNetwork]) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if (
        ip.is_loopback
        or ip.is_unspecified
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
    ):
        return True
    for net in (*_ALWAYS_BLOCKED_NETWORKS, *networks):
        if ip.version == net.version and ip in net:
            return True
    return False


def validate_outbound_url(
    url: str,
    *,
    allowed_hosts: Iterable[str] | None = None,
    require_https: bool = False,
) -> None:
    """Raise UnsafeURLError unless every address `url` resolves to is allowed.

    `allowed_hosts` pins the exact hostname (used for Apple Music); the
    address checks still run.
    """
    try:
        # Parse with httpx itself so we judge the host httpx will connect to.
        parsed = httpx.URL(url)
    except (httpx.InvalidURL, ValueError) as exc:
        raise UnsafeURLError("Server URL is not a valid URL") from exc

    allowed_schemes = ("https",) if require_https else ("http", "https")
    if parsed.scheme not in allowed_schemes:
        raise UnsafeURLError("Server URL must start with http:// or https://")

    host = parsed.host.lower().rstrip(".")
    if not host:
        raise UnsafeURLError("Server URL has no host")
    if allowed_hosts is not None and host not in {h.lower() for h in allowed_hosts}:
        raise UnsafeURLError("Server URL host is not allowed")
    if host in BLOCKED_HOSTNAMES or host.endswith(".localhost"):
        raise UnsafeURLError("Server URL host is not allowed")

    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            # inet_aton understands the legacy shorthand forms (decimal
            # "2130706433", hex "0x7f000001", "127.1") that resolvers accept.
            addresses = [ipaddress.ip_address(socket.inet_ntoa(socket.inet_aton(host)))]
        except OSError:
            addresses = []
    if not addresses:
        try:
            addresses = [ipaddress.ip_address(a) for a in _resolve_host(host)]
        except (OSError, ValueError) as exc:
            raise UnsafeURLError("Server URL host could not be resolved") from exc
    if not addresses:
        raise UnsafeURLError("Server URL host could not be resolved")

    networks = _container_networks()
    for ip in addresses:
        if _is_blocked_ip(ip, networks):
            raise UnsafeURLError("Server URL host is not allowed")
