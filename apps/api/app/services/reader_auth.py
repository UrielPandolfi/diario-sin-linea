"""Reader passwords and signed session cookies.

The token is HMAC-SHA256 over canonical JSON. The web middleware verifies the
same format with APP_SECRET. It is not the admin session cookie.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import time
from uuid import UUID

READER_COOKIE = "sl_reader"
READER_SESSION_TTL = 14 * 24 * 60 * 60
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_DUMMY_HASH: str | None = None


def normalize_email(value: str) -> str | None:
    email = value.strip().lower()
    if len(email) > 254 or _EMAIL.fullmatch(email) is None:
        return None
    return email


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${digest.hex()}"


def _dummy_hash() -> str:
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_password("not-a-real-reader-password")
    return _DUMMY_HASH


def verify_password(password: str, stored: str) -> bool:
    salt, digest = _split_hash(stored)
    if salt is None or digest is None:
        return False
    check = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return hmac.compare_digest(check, digest)


def password_matches(password: str, stored: str | None) -> bool:
    if stored is None:
        verify_password(password, _dummy_hash())
        return False
    return verify_password(password, stored)


def _split_hash(stored: str) -> tuple[bytes | None, bytes | None]:
    parts = stored.split("$")
    if len(parts) != 3 or parts[0] != "scrypt":
        return None, None
    try:
        return bytes.fromhex(parts[1]), bytes.fromhex(parts[2])
    except ValueError:
        return None, None


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes | None:
    if not value or any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for char in value):
        return None
    padded = value + "=" * ((4 - len(value) % 4) % 4)
    try:
        return base64.urlsafe_b64decode(padded.encode("ascii"))
    except Exception:
        return None


def canonical_payload(sub: str, exp: int) -> str:
    return json.dumps({"exp": exp, "sub": sub}, separators=(",", ":"), sort_keys=True)


def issue_reader_token(sub: UUID | str, secret: str, *, now: int | None = None, ttl: int = READER_SESSION_TTL) -> str:
    issued_at = int(time.time()) if now is None else int(now)
    body = _b64url(canonical_payload(str(sub), issued_at + ttl).encode("utf-8"))
    signature = hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
    return f"{body}.{_b64url(signature)}"


def read_reader_token(token: str | None, secret: str, *, now: int | None = None) -> str | None:
    if not token or not secret or token.count(".") != 1:
        return None
    body, signature = token.split(".", 1)
    expected = hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
    given = _b64url_decode(signature)
    if given is None or not hmac.compare_digest(expected, given):
        return None
    raw = _b64url_decode(body)
    if raw is None:
        return None
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    sub = payload.get("sub")
    exp = payload.get("exp")
    if not isinstance(sub, str) or not isinstance(exp, int):
        return None
    try:
        UUID(sub)
    except ValueError:
        return None
    current = int(time.time()) if now is None else int(now)
    if exp <= current:
        return None
    return sub
