import hmac
from typing import Annotated
from urllib.parse import urlparse
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.models.reader import Reader
from app.core.admin_secret import admin_session_stamp
from app.services.reader_auth import READER_COOKIE, read_reader_session

DbSession = Annotated[Session, Depends(get_db)]


def optional_reader(request: Request, db: DbSession) -> Reader | None:
    parsed = read_reader_session(request.cookies.get(READER_COOKIE), get_settings().app_secret)
    if parsed is None:
        return None
    sub, generation = parsed
    reader = db.get(Reader, UUID(sub))
    if reader is None or int(reader.session_generation or 0) != generation:
        return None
    return reader


class StaleReaderSession(Exception):
    """La cookie está firmada, pero el lector ya no existe o la generación no coincide."""


def require_reader(request: Request, db: DbSession) -> Reader:
    reader = optional_reader(request, db)
    if reader is None:
        if request.cookies.get(READER_COOKIE):
            raise StaleReaderSession()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No autenticado")
    return reader


def require_admin(request: Request) -> None:
    settings = get_settings()
    stamp = request.session.get("admin_stamp")
    expected = admin_session_stamp(settings.admin_password)
    if request.session.get("admin") is not True or not isinstance(stamp, str):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No autenticado")
    if not hmac.compare_digest(stamp, expected):
        request.session.clear()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No autenticado")


def _request_origin(request: Request) -> str | None:
    origin = (request.headers.get("origin") or "").strip()
    if origin:
        return origin
    referer = (request.headers.get("referer") or "").strip()
    if not referer:
        return None
    parsed = urlparse(referer)
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def require_admin_origin(request: Request) -> None:
    require_admin(request)
    origin = _request_origin(request)
    allowed = get_settings().cors_origin_list()
    if not origin or origin not in allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="origin_not_allowed")
