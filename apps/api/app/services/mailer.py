"""Envío por la API HTTPS de Resend. Si falta configuración o falla, no afirma que salió."""

from __future__ import annotations

import logging
from urllib.parse import urlsplit

import httpx

from app.core.config import Settings

logger = logging.getLogger(__name__)

_RESEND_URL = "https://api.resend.com/emails"
_DEFAULT_REPLY_TO = "contacto@sinlinea.ar"


def mail_origin(settings: Settings) -> str | None:
    raw = (settings.app_base_url or "").strip() or (settings.site_url or "").strip()
    raw = raw.rstrip("/")
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return raw


def origin_is_public(origin: str) -> bool:
    parsed = urlsplit(origin)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https" or not host:
        return False
    if host in {"localhost", "127.0.0.1", "::1"}:
        return False
    if host.endswith(".vercel.app") or host.endswith(".railway.app"):
        return False
    return True


def mail_configured(settings: Settings) -> bool:
    key = (settings.resend_api_key or "").strip()
    sender = (settings.email_from or "").strip()
    origin = mail_origin(settings)
    return bool(key and sender and origin and origin_is_public(origin))


def from_header(settings: Settings) -> str:
    raw = (settings.email_from or "").strip()
    if "<" in raw and raw.endswith(">"):
        return raw
    return f"Sin Línea <{raw}>"


def reply_to_address(settings: Settings) -> str:
    value = (settings.email_reply_to or "").strip()
    return value or _DEFAULT_REPLY_TO


def send_email(
    settings: Settings,
    *,
    to: str,
    subject: str,
    body: str,
    html: str | None = None,
) -> bool:
    if not mail_configured(settings):
        return False
    payload: dict[str, str | list[str]] = {
        "from": from_header(settings),
        "to": [to],
        "reply_to": reply_to_address(settings),
        "subject": subject,
        "text": body,
    }
    if html:
        payload["html"] = html
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(
                _RESEND_URL,
                headers={
                    "Authorization": f"Bearer {settings.resend_api_key.strip()}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        logger.error("resend rejected the message status=%s", exc.response.status_code)
        return False
    except httpx.HTTPError:
        logger.error("resend request failed")
        return False
    return True
