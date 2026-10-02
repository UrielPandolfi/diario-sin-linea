"""Tokens de un solo uso para restablecer la contraseña. Se guarda el hash, no el token."""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import utc_now
from app.models.reader import Reader
from app.models.reader_password_reset import ReaderPasswordReset
from app.services.reader_auth import hash_password

RESET_TTL = timedelta(hours=1)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_reset(session: Session, reader: Reader) -> str:
    raw = secrets.token_urlsafe(32)
    session.add(
        ReaderPasswordReset(
            reader_id=reader.id,
            token_hash=_hash_token(raw),
            expires_at=utc_now() + RESET_TTL,
        )
    )
    session.flush()
    return raw


def confirm_reset(session: Session, token: str, password: str) -> Reader | None:
    row = session.scalar(
        select(ReaderPasswordReset).where(ReaderPasswordReset.token_hash == _hash_token(token))
    )
    now = utc_now()
    if row is None or row.used_at is not None or row.expires_at <= now:
        return None
    reader = session.get(Reader, row.reader_id)
    if reader is None:
        return None
    row.used_at = now
    pending = session.scalars(
        select(ReaderPasswordReset).where(
            ReaderPasswordReset.reader_id == reader.id,
            ReaderPasswordReset.used_at.is_(None),
        )
    ).all()
    for other in pending:
        other.used_at = now
    reader.password_hash = hash_password(password)
    reader.session_generation = int(reader.session_generation or 0) + 1
    session.flush()
    return reader
