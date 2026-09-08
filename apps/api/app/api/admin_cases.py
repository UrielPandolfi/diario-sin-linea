from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.api.deps import DbSession, require_admin, require_admin_origin
from app.domain.enums import CaseOutcome, CaseReason, CaseStatus, EditorialRevisionKind
from app.models import ReaderCase
from app.repositories import ArticleRepository
from app.services.case_service import CaseService, CaseServiceError, follow_up_url
from app.services.editorial_service import EditorialService, EditorialServiceError

router = APIRouter(prefix="/api/v1/admin", tags=["admin-cases"])


def _http_case(exc: CaseServiceError) -> HTTPException:
    return HTTPException(status_code=exc.http_status, detail=exc.code)


def _http_edit(exc: EditorialServiceError) -> HTTPException:
    return HTTPException(status_code=exc.http_status, detail=exc.code)


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None


def _case_list_out(row: ReaderCase) -> dict:
    article = row.article
    return {
        "id": str(row.id),
        "public_code": row.public_code,
        "status": row.status.value,
        "reason": row.reason.value,
        "outcome": row.outcome.value if row.outcome is not None else None,
        "created_at": _iso(row.created_at),
        "article_id": str(row.article_id) if row.article_id else None,
        "article_slug": article.slug if article is not None else None,
        "headline": article.headline if article is not None else None,
    }


def _version_out(version) -> dict | None:
    if version is None:
        return None
    return {
        "id": str(version.id),
        "version_number": version.version_number,
        "headline": version.headline,
        "summary": version.summary,
        "body": version.body,
        "body_blocks": version.body_blocks,
        "published_at": _iso(version.published_at),
        "change_reason": version.change_reason,
        "created_at": _iso(version.created_at),
    }


class NoteBody(BaseModel):
    note: str = Field(min_length=1, max_length=4000)


class ResolveBody(BaseModel):
    outcome: CaseOutcome
    public_resolution: str = Field(min_length=1, max_length=4000)
    linked_correction_id: UUID | None = None


class EditorialReviseBody(BaseModel):
    base_published_version: int
    kind: EditorialRevisionKind
    headline: str
    summary: str
    body: str
    public_notice: str | None = None
    show_near_title: bool = False
    reader_case_id: UUID | None = None


@router.get("/cases", dependencies=[Depends(require_admin)])
def list_cases(
    db: DbSession,
    status_filter: str | None = Query(default=None, alias="status"),
    reason: str | None = None,
    article_id: UUID | None = None,
    limit: int = Query(default=50, ge=1, le=100),
) -> list[dict]:
    if status_filter:
        try:
            CaseStatus(status_filter)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="invalid_status") from exc
    if reason:
        try:
            CaseReason(reason)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="invalid_reason") from exc
    rows = CaseService(db).list_filtered(
        status=status_filter,
        reason=reason,
        article_id=article_id,
        limit=limit,
    )
    return [_case_list_out(row) for row in rows]


@router.get("/cases/{case_id}", dependencies=[Depends(require_admin)])
def get_case(case_id: UUID, db: DbSession) -> dict:
    row = CaseService(db).load_detail(case_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Caso no encontrado")
    return {
        **_case_list_out(row),
        "message": row.message,
        "link_url": row.link_url,
        "email": row.email,
        "public_resolution": row.public_resolution,
        "reviewing_at": _iso(row.reviewing_at),
        "resolved_at": _iso(row.resolved_at),
        "reported_version_number": row.reported_version_number,
        "follow_up_url": follow_up_url(row.access_token),
        "linked_correction_id": str(row.linked_correction_id) if row.linked_correction_id else None,
        "reported_version": _version_out(row.reported_version),
        "actions": [
            {
                "id": str(action.id),
                "action_type": action.action_type.value,
                "actor": action.actor.value,
                "internal_note": action.internal_note,
                "from_status": action.from_status,
                "to_status": action.to_status,
                "created_at": _iso(action.created_at),
            }
            for action in sorted(row.actions, key=lambda item: item.created_at)
        ],
    }


@router.post("/cases/{case_id}/review", dependencies=[Depends(require_admin_origin)])
def review_case(case_id: UUID, db: DbSession) -> dict:
    try:
        row = CaseService(db).mark_reviewing(case_id)
    except CaseServiceError as exc:
        raise _http_case(exc) from exc
    return {"id": str(row.id), "status": row.status.value}


@router.post("/cases/{case_id}/notes", dependencies=[Depends(require_admin_origin)])
def add_case_note(case_id: UUID, payload: NoteBody, db: DbSession) -> dict:
    try:
        row = CaseService(db).add_note(case_id, payload.note)
    except CaseServiceError as exc:
        raise _http_case(exc) from exc
    return {"id": str(row.id), "ok": True}


@router.post("/cases/{case_id}/resolve", dependencies=[Depends(require_admin_origin)])
def resolve_case(case_id: UUID, payload: ResolveBody, db: DbSession) -> dict:
    try:
        row = CaseService(db).resolve(
            case_id,
            outcome=payload.outcome,
            public_resolution=payload.public_resolution,
            linked_correction_id=payload.linked_correction_id,
        )
    except CaseServiceError as exc:
        raise _http_case(exc) from exc
    return {
        "id": str(row.id),
        "status": row.status.value,
        "outcome": row.outcome.value if row.outcome else None,
    }


@router.get("/articles/{article_id}/versions/{version_number}", dependencies=[Depends(require_admin)])
def get_article_version(article_id: UUID, version_number: int, db: DbSession) -> dict:
    version = ArticleRepository(db).get_version(article_id, version_number)
    if version is None:
        raise HTTPException(status_code=404, detail="Versión no encontrada")
    payload = _version_out(version)
    if payload is None:
        raise HTTPException(status_code=404, detail="Versión no encontrada")
    return payload


@router.post("/events/{event_id}/editorial-revise", dependencies=[Depends(require_admin_origin)])
def editorial_revise(event_id: UUID, payload: EditorialReviseBody, db: DbSession) -> dict:
    try:
        return EditorialService(db).revise(
            event_id,
            base_published_version=payload.base_published_version,
            kind=payload.kind,
            headline=payload.headline,
            summary=payload.summary,
            body=payload.body,
            public_notice=payload.public_notice,
            show_near_title=payload.show_near_title,
            reader_case_id=payload.reader_case_id,
        )
    except EditorialServiceError as exc:
        raise _http_edit(exc) from exc
