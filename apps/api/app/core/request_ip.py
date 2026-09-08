from __future__ import annotations

import ipaddress

from fastapi import Request

from app.core.config import Settings


def _host_matches(host: str, allowed: str) -> bool:
    if allowed == "*":
        return True
    try:
        network = ipaddress.ip_network(allowed, strict=False)
        return ipaddress.ip_address(host) in network
    except ValueError:
        return host == allowed


def client_ip(request: Request, settings: Settings) -> str:
    host = request.client.host if request.client is not None else "unknown"
    trusted = settings.trusted_proxy_list()
    if not trusted:
        return host
    if not any(_host_matches(host, item) for item in trusted):
        return host
    forwarded = (request.headers.get("x-forwarded-for") or "").strip()
    if not forwarded:
        return host
    first = forwarded.split(",")[0].strip()
    return first or host
