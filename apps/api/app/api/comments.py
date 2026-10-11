from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.api.deps import DbSession, require_reader
from app.core.config import get_settings
from app.core.request_ip import client_ip
from app.models.reader import Reader
from app.services.comment_rate_limit import allow_comment
from app.services.comment_service import CommentError, CommentService

router = APIRouter(prefix="/api/v1", tags=["comments"])


class CommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=1000)
    anonymous: bool = False
    parent_id: UUID | None = None


def _http(exc: CommentError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=exc.code)


@router.get("/articles/{key}/comments")
def list_comments(key: str, db: DbSession) -> dict:
    items = CommentService(db).list_public(key)
    if items is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="article_not_found")
    return {"items": items}


@router.post("/articles/{key}/comments", status_code=status.HTTP_201_CREATED)
def create_comment(
    key: str,
    payload: CommentCreate,
    request: Request,
    db: DbSession,
    reader: Annotated[Reader, Depends(require_reader)],
) -> dict:
    settings = get_settings()
    if not allow_comment(str(reader.id), client_ip(request, settings)):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="rate_limited")
    try:
        return CommentService(db).create(
            key=key,
            reader=reader,
            body=payload.body,
            anonymous=payload.anonymous,
            parent_id=payload.parent_id,
        )
    except CommentError as exc:
        raise _http(exc) from exc
