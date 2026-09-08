from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.api.deps import DbSession
from app.core.config import get_settings
from app.core.request_ip import client_ip
from app.domain.enums import CaseReason
from app.services.case_rate_limit import allow_case_submit
from app.services.case_service import CaseService, CaseServiceError, follow_up_url, public_case_out

router = APIRouter(prefix="/api/v1", tags=["cases"])


class CaseCreateBody(BaseModel):
    article_id: UUID | None = None
    article_slug: str | None = None
    reported_version_number: int | None = None
    reason: CaseReason
    message: str = Field(min_length=1, max_length=4000)
    link_url: str | None = None
    email: str | None = None
    website: str | None = None
    idempotency_key: UUID | None = None


def _http(exc: CaseServiceError) -> HTTPException:
    return HTTPException(status_code=exc.http_status, detail=exc.code)


@router.post("/cases", status_code=status.HTTP_201_CREATED)
def create_case(
    payload: CaseCreateBody,
    request: Request,
    db: DbSession,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    if (payload.website or "").strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_request")
    key = payload.idempotency_key
    if idempotency_key:
        try:
            key = UUID(idempotency_key)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid_idempotency_key") from exc
    if key is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="idempotency_key_required")

    settings = get_settings()
    ip = client_ip(request, settings)
    article_id = payload.article_id
    if not allow_case_submit(ip, article_id):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="rate_limited")

    service = CaseService(db)
    try:
        row = service.create(
            idempotency_key=key,
            reason=payload.reason,
            message=payload.message,
            ip=ip,
            article_id=payload.article_id,
            article_slug=payload.article_slug,
            reported_version_number=payload.reported_version_number,
            link_url=payload.link_url,
            email=payload.email,
        )
    except CaseServiceError as exc:
        raise _http(exc) from exc
    return {
        "public_code": row.public_code,
        "follow_up_url": follow_up_url(row.access_token),
    }


@router.get("/cases/follow-up/{token}")
def follow_up(token: str, db: DbSession) -> JSONResponse:
    row = CaseService(db).get_by_token(token)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Caso no encontrado")
    return JSONResponse(
        public_case_out(row),
        headers={
            "Cache-Control": "private, no-store",
            "Referrer-Policy": "no-referrer",
            "X-Robots-Tag": "noindex, nofollow",
        },
    )
