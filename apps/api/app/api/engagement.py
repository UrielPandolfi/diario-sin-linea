from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse

from app.api.deps import DbSession, require_reader
from app.models.reader import Reader
from app.services.feed_ranking import DEFAULT_LIMIT, FeedRankingService, clamp_limit
from app.services.reader_engagement import (
    event_is_liked,
    event_is_saved,
    like_event,
    record_read,
    save_event,
    unlike_event,
    unsave_event,
)

router = APIRouter(prefix="/api/v1/articles", tags=["engagement"])

_NO_STORE = {"Cache-Control": "private, no-store"}


def _public_event_id(db: DbSession, key: str) -> UUID:
    event_id = FeedRankingService(db).public_event_id(key)
    if event_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artículo no encontrado")
    return event_id


@router.get("/{key}/like")
def get_like(
    key: str,
    db: DbSession,
    reader: Annotated[Reader, Depends(require_reader)],
) -> JSONResponse:
    event_id = _public_event_id(db, key)
    return JSONResponse({"liked": event_is_liked(db, reader.id, event_id)}, headers=_NO_STORE)


@router.put("/{key}/like")
def put_like(
    key: str,
    db: DbSession,
    reader: Annotated[Reader, Depends(require_reader)],
) -> JSONResponse:
    event_id = _public_event_id(db, key)
    like_event(db, reader.id, event_id)
    return JSONResponse({"liked": True}, headers=_NO_STORE)


@router.delete("/{key}/like")
def delete_like(
    key: str,
    db: DbSession,
    reader: Annotated[Reader, Depends(require_reader)],
) -> JSONResponse:
    event_id = _public_event_id(db, key)
    unlike_event(db, reader.id, event_id)
    return JSONResponse({"liked": False}, headers=_NO_STORE)


@router.post("/{key}/read", status_code=status.HTTP_204_NO_CONTENT)
def post_read(
    key: str,
    db: DbSession,
    reader: Annotated[Reader, Depends(require_reader)],
) -> None:
    event_id = _public_event_id(db, key)
    record_read(db, reader.id, event_id)


@router.get("/{key}/save")
def get_save(
    key: str,
    db: DbSession,
    reader: Annotated[Reader, Depends(require_reader)],
) -> JSONResponse:
    event_id = _public_event_id(db, key)
    return JSONResponse({"saved": event_is_saved(db, reader.id, event_id)}, headers=_NO_STORE)


@router.put("/{key}/save")
def put_save(
    key: str,
    db: DbSession,
    reader: Annotated[Reader, Depends(require_reader)],
) -> JSONResponse:
    event_id = _public_event_id(db, key)
    save_event(db, reader.id, event_id)
    return JSONResponse({"saved": True}, headers=_NO_STORE)


@router.delete("/{key}/save")
def delete_save(
    key: str,
    db: DbSession,
    reader: Annotated[Reader, Depends(require_reader)],
) -> JSONResponse:
    event_id = _public_event_id(db, key)
    unsave_event(db, reader.id, event_id)
    return JSONResponse({"saved": False}, headers=_NO_STORE)


saved_router = APIRouter(prefix="/api/v1", tags=["saved"])


@saved_router.get("/saved")
def list_saved(
    db: DbSession,
    reader: Annotated[Reader, Depends(require_reader)],
    cursor: str | None = None,
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=50),
) -> JSONResponse:
    try:
        payload = FeedRankingService(db).saved(reader_id=reader.id, limit=clamp_limit(limit), cursor=cursor)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc) or "invalid_request") from exc
    return JSONResponse(payload, headers=_NO_STORE)
