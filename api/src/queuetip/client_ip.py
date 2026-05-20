"""Client IP resolution with X-Forwarded-For trust for reverse proxies."""

import ipaddress
from typing import Union

from django.conf import settings as dj_settings

from starlette.requests import Request
from starlette.websockets import WebSocket


def _is_trusted_proxy(addr: str, trusted: list[str]) -> bool:
    """Return True if `addr` falls within any entry in `trusted`."""
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    for entry in trusted:
        try:
            if ip in ipaddress.ip_network(entry, strict=False):
                return True
        except ValueError:
            continue
    return False


def get_client_ip(request: Union[Request, WebSocket]) -> str:
    """Return the real client IP, peeling trusted proxy hops from XFF.

    When the direct connection arrives from a trusted proxy (per
    QUEUETIP_TRUSTED_PROXIES), the X-Forwarded-For header is parsed
    right-to-left and each hop that matches a trusted CIDR is stripped.
    The first untrusted IP becomes the effective client address.

    When no trusted proxies are configured, or the direct connection is not
    from a trusted proxy, `request.client.host` is returned as-is. This
    prevents an untrusted intermediary from spoofing the header.
    """
    direct: str = request.client.host if request.client is not None else "unknown"

    try:
        trusted: list[str] = dj_settings.QUEUETIP_TRUSTED_PROXIES
    except AttributeError:
        trusted = []
    if not trusted or not _is_trusted_proxy(direct, trusted):
        return direct

    xff: str | None = request.headers.get("x-forwarded-for")
    if not xff:
        return direct

    # XFF is a comma-separated list oldest-first: "client, proxy1, proxy2".
    # The rightmost entry is appended by the last trusted proxy, so peel from
    # the right — dropping each entry that is itself a trusted proxy — and
    # return the first untrusted IP we encounter.
    hops = [h.strip() for h in xff.split(",")]
    # Append the direct connection so we process all hops uniformly.
    hops.append(direct)

    for hop in reversed(hops):
        if not _is_trusted_proxy(hop, trusted):
            return hop

    # Every hop in the chain is trusted (unusual but valid). Fall back to the
    # leftmost entry — the closest thing to the origin we have.
    return hops[0]
