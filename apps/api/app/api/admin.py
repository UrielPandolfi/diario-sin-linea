from datetime import timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from app.api.deps import DbSession, require_admin
from app.core.clock import utc_now
from app.core.config import get_settings
from app.domain.enums import IngestionMethod
from app.repositories import (
    ArticleRepository,
    EntityRepository,
    EventRepository,
    PipelineRunRepository,
    SourceItemRepository,
    SourceRepository,
)
from app.schemas import SourceCreate, SourceUpdate
from app.services.source_service import SourceService
from app.workers.tasks import (
    audit_event_article,
    poll_source,
    research_event,
    resolve_event_claims,
    verify_event_claims,
    write_event_article,
)

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


class LoginBody(BaseModel):
    password: str


class SourceWrite(BaseModel):
    name: str
    domain: str | None = None
    homepage_url: str | None = None
    source_type: str | None = None
    preferred_ingestion_method: IngestionMethod = IngestionMethod.RSS
    feed_url: str | None = None
    endpoint_url: str | None = None
    is_monitored: bool = False
    is_enabled: bool = True


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None


def _source_out(source) -> dict:
    return {
        "id": str(source.id),
        "name": source.name,
        "domain": source.domain,
        "homepage_url": source.homepage_url,
        "source_type": source.source_type,
        "preferred_ingestion_method": source.preferred_ingestion_method.value,
        "feed_url": source.feed_url,
        "endpoint_url": source.endpoint_url,
        "is_monitored": source.is_monitored,
        "is_enabled": source.is_enabled,
        "last_success_at": _iso(source.last_success_at),
        "last_failure_at": _iso(source.last_failure_at),
        "failure_count": source.failure_count,
    }


def _item_out(item) -> dict:
    return {
        "id": str(item.id),
        "source_id": str(item.source_id),
        "url": item.url,
        "canonical_url": item.canonical_url,
        "title": item.title,
        "published_at": _iso(item.published_at),
        "detected_at": _iso(item.detected_at),
        "processing_status": item.processing_status.value,
    }


def _claim_out(claim) -> dict:
    return {
        "id": str(claim.id),
        "canonical_text": claim.canonical_text,
        "status": claim.status.value,
        "importance": claim.importance.value,
        "claim_type": claim.claim_type,
        "evidence": [
            {
                "evidence_type": row.evidence_type.value,
                "excerpt": row.excerpt,
                "source_item_id": str(row.source_item_id),
            }
            for row in claim.evidence
        ],
    }


def _article_out(article) -> dict:
    return {
        "id": str(article.id),
        "headline": article.headline,
        "summary": article.summary,
        "body": article.body,
        "status": article.status.value,
        "current_version": article.current_version,
        "slug": article.slug,
    }


def _audit_out(runs) -> dict | None:
    for run in runs:
        if run.stage != "auditing":
            continue
        meta = run.metadata_json or {}
        return {
            "run_id": str(run.id),
            "status": run.status.value,
            "passed": meta.get("passed"),
            "cap_exhausted": bool(meta.get("cap_exhausted")),
            "rewrite_count": meta.get("rewrite_count"),
            "audit_count": meta.get("audit_count"),
            "issues": meta.get("issues") or [],
            "reason": meta.get("reason"),
            "error_message": run.error_message,
        }
    return None


def _writing_or_auditing_running(db, event_id: UUID):
    repo = PipelineRunRepository(db)
    if repo.get_running(event_id, "writing") is not None:
        return True
    return repo.get_running(event_id, "auditing") is not None


def _event_out(event) -> dict:
    return {
        "id": str(event.id),
        "title_internal": event.title_internal,
        "event_type": event.event_type,
        "status": event.status.value,
        "locality": event.locality,
        "province": event.province,
        "short_summary": event.short_summary,
        "detected_at": _iso(event.detected_at),
        "started_at": _iso(event.started_at),
    }


@router.post("/login")
def login(payload: LoginBody, request: Request) -> dict:
    settings = get_settings()
    if not settings.admin_password or payload.password != settings.admin_password:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Contraseña incorrecta")
    request.session["admin"] = True
    return {"ok": True}


@router.post("/logout")
def logout(request: Request) -> dict:
    request.session.clear()
    return {"ok": True}


@router.get("/me", dependencies=[Depends(require_admin)])
def me() -> dict:
    return {"ok": True, "role": "admin"}


@router.get("/stats", dependencies=[Depends(require_admin)])
def stats(db: DbSession) -> dict:
    since = utc_now() - timedelta(hours=24)
    return {
        "monitored_sources": SourceRepository(db).count_monitored(),
        "source_items_24h": SourceItemRepository(db).count_since(since),
        "events_24h": EventRepository(db).count_since(since),
        "failed_runs_24h": PipelineRunRepository(db).count_failed_since(since),
    }


@router.get("/sources", dependencies=[Depends(require_admin)])
def list_sources(db: DbSession) -> list[dict]:
    return [_source_out(source) for source in SourceService(db).list_all()]


@router.post("/sources", dependencies=[Depends(require_admin)], status_code=status.HTTP_201_CREATED)
def create_source(payload: SourceWrite, db: DbSession) -> dict:
    source = SourceService(db).create(SourceCreate(**payload.model_dump()))
    return _source_out(source)


@router.get("/sources/{source_id}", dependencies=[Depends(require_admin)])
def get_source(source_id: UUID, db: DbSession) -> dict:
    source = SourceService(db).get(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Fuente no encontrada")
    return _source_out(source)


@router.patch("/sources/{source_id}", dependencies=[Depends(require_admin)])
def patch_source(source_id: UUID, payload: SourceUpdate, db: DbSession) -> dict:
    service = SourceService(db)
    source = service.get(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Fuente no encontrada")
    updated = service.update(source, payload)
    return _source_out(updated)


@router.post("/sources/{source_id}/poll", dependencies=[Depends(require_admin)], status_code=status.HTTP_202_ACCEPTED)
def enqueue_poll(source_id: UUID, db: DbSession) -> dict:
    source = SourceService(db).get(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Fuente no encontrada")
    poll_source.delay(str(source_id))
    return {"queued": True, "source_id": str(source_id)}


@router.get("/source-items", dependencies=[Depends(require_admin)])
def list_items(db: DbSession, source_id: UUID | None = None, limit: int = 50) -> list[dict]:
    items = SourceItemRepository(db).list_recent(source_id=source_id, limit=min(limit, 100))
    return [_item_out(item) for item in items]


@router.get("/events", dependencies=[Depends(require_admin)])
def list_events(db: DbSession, limit: int = 50) -> list[dict]:
    events = EventRepository(db).list_recent(limit=min(limit, 100))
    return [_event_out(event) for event in events]


@router.get("/events/{event_id}", dependencies=[Depends(require_admin)])
def get_event(event_id: UUID, db: DbSession) -> dict:
    event = EventRepository(db).get_with_details(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Suceso no encontrado")
    entities = {entity.id: entity for entity in EntityRepository(db).list_for_event(event_id)}
    runs = PipelineRunRepository(db).list_for_event(event_id)
    article = ArticleRepository(db).get_by_event_id(event_id)
    return {
        **_event_out(event),
        "country_code": event.country_code,
        "neighborhood": event.neighborhood,
        "address_text": event.address_text,
        "sources": [
            {
                "relation_type": link.relation_type.value,
                "is_primary": link.is_primary,
                "source_item": _item_out(link.source_item) if link.source_item is not None else None,
            }
            for link in event.event_sources
        ],
        "entities": [
            {
                "id": str(link.entity_id),
                "name": entities[link.entity_id].name if link.entity_id in entities else None,
                "entity_type": (
                    entities[link.entity_id].entity_type.value if link.entity_id in entities else None
                ),
                "role": link.role,
            }
            for link in event.event_entities
        ],
        "claims": [_claim_out(claim) for claim in event.claims],
        "article": _article_out(article) if article is not None else None,
        "audit": _audit_out(runs),
        "pipeline_runs": [
            {
                "id": str(run.id),
                "stage": run.stage,
                "status": run.status.value,
                "attempt": run.attempt,
                "error_message": run.error_message,
                "started_at": _iso(run.started_at),
                "finished_at": _iso(run.finished_at),
            }
            for run in runs
        ],
    }


@router.post(
    "/events/{event_id}/research",
    dependencies=[Depends(require_admin)],
    status_code=status.HTTP_202_ACCEPTED,
)
def enqueue_research(event_id: UUID, db: DbSession) -> dict:
    event = EventRepository(db).get(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Suceso no encontrado")
    running = PipelineRunRepository(db).get_running(event_id, "research")
    if running is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="already_running")
    research_event.delay(str(event_id), "admin")
    return {"queued": True, "event_id": str(event_id)}


@router.post(
    "/events/{event_id}/claims",
    dependencies=[Depends(require_admin)],
    status_code=status.HTTP_202_ACCEPTED,
)
def enqueue_claims(event_id: UUID, db: DbSession) -> dict:
    event = EventRepository(db).get(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Suceso no encontrado")
    running = PipelineRunRepository(db).get_running(event_id, "claim_resolution")
    if running is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="already_running")
    resolve_event_claims.delay(str(event_id), "admin")
    return {"queued": True, "event_id": str(event_id)}


@router.post(
    "/events/{event_id}/verify",
    dependencies=[Depends(require_admin)],
    status_code=status.HTTP_202_ACCEPTED,
)
def enqueue_verify(event_id: UUID, db: DbSession) -> dict:
    event = EventRepository(db).get(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Suceso no encontrado")
    running = PipelineRunRepository(db).get_running(event_id, "verification")
    if running is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="already_running")
    verify_event_claims.delay(str(event_id), "admin")
    return {"queued": True, "event_id": str(event_id)}


@router.post(
    "/events/{event_id}/write",
    dependencies=[Depends(require_admin)],
    status_code=status.HTTP_202_ACCEPTED,
)
def enqueue_write(event_id: UUID, db: DbSession) -> dict:
    event = EventRepository(db).get(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Suceso no encontrado")
    running = _writing_or_auditing_running(db, event_id)
    if running:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="already_running")
    write_event_article.delay(str(event_id), "admin")
    return {"queued": True, "event_id": str(event_id)}


@router.post(
    "/events/{event_id}/audit",
    dependencies=[Depends(require_admin)],
    status_code=status.HTTP_202_ACCEPTED,
)
def enqueue_audit(event_id: UUID, db: DbSession) -> dict:
    event = EventRepository(db).get(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Suceso no encontrado")
    if _writing_or_auditing_running(db, event_id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="already_running")
    audit_event_article.delay(str(event_id), "admin")
    return {"queued": True, "event_id": str(event_id)}
