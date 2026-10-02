from __future__ import annotations

import hashlib
import logging

from app.core.config import get_settings
from app.services.case_rate_limit import _redis_client

logger = logging.getLogger(__name__)

_WINDOW_SECONDS = 60 * 60
_IP_LIMIT = 5
_EMAIL_LIMIT = 3


def _email_key(email: str) -> str:
    digest = hashlib.sha256(f"{email}:{get_settings().app_secret}".encode()).hexdigest()
    return f"sin_linea:password-reset:email:{digest}"


def allow_password_reset(ip: str, email: str) -> bool:
    try:
        with _redis_client() as client:
            ip_key = f"sin_linea:password-reset:ip:{ip}"
            ip_count = int(client.incr(ip_key))
            if ip_count == 1:
                client.expire(ip_key, _WINDOW_SECONDS)
            email_key = _email_key(email)
            email_count = int(client.incr(email_key))
            if email_count == 1:
                client.expire(email_key, _WINDOW_SECONDS)
            if ip_count <= _IP_LIMIT and email_count <= _EMAIL_LIMIT:
                return True
            return False
    except Exception:
        logger.exception("password reset redis failed; denying")
        return False
