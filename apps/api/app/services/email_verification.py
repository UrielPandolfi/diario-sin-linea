"""Tokens de un solo uso para confirmar el email. Se guarda el hash, no el token."""

from __future__ import annotations

import secrets
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import utc_now
from app.models.reader import Reader
from app.models.reader_email_verification import ReaderEmailVerification
from app.services.auth_tokens import hash_token

VERIFICATION_TTL = timedelta(hours=24)


def issue_verification(session: Session, reader: Reader) -> str:
    raw = secrets.token_urlsafe(32)
    now = utc_now()
    pending = session.scalars(
        select(ReaderEmailVerification).where(
            ReaderEmailVerification.reader_id == reader.id,
            ReaderEmailVerification.used_at.is_(None),
        )
    ).all()
    for row in pending:
        row.used_at = now
    session.add(
        ReaderEmailVerification(
            reader_id=reader.id,
            token_hash=hash_token(raw),
            expires_at=now + VERIFICATION_TTL,
        )
    )
    session.flush()
    return raw


def forget_verification_token(session: Session, token: str) -> None:
    row = session.scalar(
        select(ReaderEmailVerification).where(ReaderEmailVerification.token_hash == hash_token(token))
    )
    if row is not None:
        session.delete(row)
    session.flush()


def confirm_verification(session: Session, token: str) -> Reader | None:
    row = session.scalar(
        select(ReaderEmailVerification).where(ReaderEmailVerification.token_hash == hash_token(token))
    )
    now = utc_now()
    if row is None or row.used_at is not None or row.expires_at <= now:
        return None
    reader = session.get(Reader, row.reader_id)
    if reader is None:
        return None
    row.used_at = now
    pending = session.scalars(
        select(ReaderEmailVerification).where(
            ReaderEmailVerification.reader_id == reader.id,
            ReaderEmailVerification.used_at.is_(None),
        )
    ).all()
    for other in pending:
        other.used_at = now
    reader.email_verified_at = now
    session.flush()
    return reader
