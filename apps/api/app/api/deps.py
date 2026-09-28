from typing import Annotated
from urllib.parse import urlparse
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.models.reader import Reader
from app.services.reader_auth import READER_COOKIE, read_reader_token

DbSession = Annotated[Session, Depends(get_db)]


def optional_reader(request: Request, db: DbSession) -> Reader | None:
    sub = read_reader_token(request.cookies.get(READER_COOKIE), get_settings().app_secret)
    if sub is None:
        return None
    return db.get(Reader, UUID(sub))


def require_reader(request: Request, db: DbSession) -> Reader:
    reader = optional_reader(request, db)
    if reader is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No autenticado")
    return reader


def require_admin(request: Request) -> None:
    if request.session.get("admin") is not True:
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
