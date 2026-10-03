from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse

from app.api.deps import DbSession, require_reader
from app.models.reader import Reader
from app.services.feed_ranking import clamp_limit
from app.services.rejected_drafts import RejectedDraftQuery

router = APIRouter(prefix="/api/v1/transparency", tags=["transparency"])

_PRIVATE = {
    "Cache-Control": "private, no-store",
    "X-Robots-Tag": "noindex, nofollow",
}


def _private(payload: dict, *, code: int = status.HTTP_200_OK) -> JSONResponse:
    return JSONResponse(payload, status_code=code, headers=_PRIVATE)


@router.get("/rejected-drafts")
def list_rejected_drafts(
    db: DbSession,
    reader: Annotated[Reader, Depends(require_reader)],
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=50),
) -> JSONResponse:
    del reader
    try:
        payload = RejectedDraftQuery(db).list_page(limit=clamp_limit(limit), cursor=cursor)
    except ValueError as exc:
        detail = "invalid_cursor" if str(exc) == "invalid_cursor" else "invalid_request"
        return _private({"detail": detail}, code=status.HTTP_400_BAD_REQUEST)
    return _private(payload)


@router.get("/rejected-drafts/{article_id}")
def get_rejected_draft(
    article_id: UUID,
    db: DbSession,
    reader: Annotated[Reader, Depends(require_reader)],
) -> JSONResponse:
    del reader
    payload = RejectedDraftQuery(db).get(article_id)
    if payload is None:
        return _private({"detail": "No encontrado"}, code=status.HTTP_404_NOT_FOUND)
    return _private(payload)
