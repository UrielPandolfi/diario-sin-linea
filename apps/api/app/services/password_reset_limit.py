from __future__ import annotations

import hashlib
import logging

from app.core.config import get_settings
from app.services.case_rate_limit import _redis_client

logger = logging.getLogger(__name__)

_WINDOW_SECONDS = 60 * 60
_IP_LIMIT = 5
_EMAIL_LIMIT = 3


def _allow(prefix: str, ip: str, email: str) -> bool:
    try:
        with _redis_client() as client:
            ip_key = f"{prefix}:ip:{ip}"
            ip_count = int(client.incr(ip_key))
            if ip_count == 1:
                client.expire(ip_key, _WINDOW_SECONDS)
            email_key = f"{prefix}:email:{hashlib.sha256(f'{email}:{get_settings().app_secret}'.encode()).hexdigest()}"
            email_count = int(client.incr(email_key))
            if email_count == 1:
                client.expire(email_key, _WINDOW_SECONDS)
            return ip_count <= _IP_LIMIT and email_count <= _EMAIL_LIMIT
    except Exception:
        logger.exception("transactional mail redis failed; denying")
        return False


def allow_password_reset(ip: str, email: str) -> bool:
    return _allow("sin_linea:password-reset", ip, email)


def allow_email_verification(ip: str, email: str) -> bool:
    return _allow("sin_linea:email-verification", ip, email)
