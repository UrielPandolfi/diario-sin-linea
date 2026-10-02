"""Contraseña de administración.

No hay fallback de desarrollo. Un valor vacío o conocido impide arrancar.
"""

from __future__ import annotations

import hashlib
import hmac

DEV_ADMIN_PASSWORDS = frozenset({"dev-admin", "admin", "password", "changeme", "change-me"})
MIN_ADMIN_PASSWORD_LENGTH = 32


def assert_admin_password(password: str) -> None:
    value = (password or "").strip()
    if (
        not value
        or value.casefold() in DEV_ADMIN_PASSWORDS
        or len(value) < MIN_ADMIN_PASSWORD_LENGTH
    ):
        raise RuntimeError(
            "ADMIN_PASSWORD vacía, corta o de desarrollo. El proceso no arranca."
        )


def admin_passwords_match(given: str, expected: str) -> bool:
    if not expected:
        return False
    return hmac.compare_digest(
        hashlib.sha256(given.encode("utf-8")).digest(),
        hashlib.sha256(expected.encode("utf-8")).digest(),
    )


def admin_session_stamp(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()
