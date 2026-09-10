from datetime import datetime, timedelta
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.api.deps import DbSession, require_admin, require_admin_origin
from app.core.clock import utc_now
from app.core.config import get_settings
from app.core.source_content import body_source_from_item, has_extracted_body
from app.domain.enums import IngestionMethod
from app.repositories import (
    ArticleRepository,
    EntityRepository,
    EventRepository,
    LlmUsageRepository,
    PipelineRunRepository,
    SourceItemRepository,
    SourceRepository,
)
from app.services.claim_card_presentation import presentation_for_claim, public_presentation_payload
from app.services.editorial_label_policy import editorial_public_payload, labels_for_event_claims
from app.services.verification_outcome import verification_view_for_event
from app.services.cost_service import aggregate_usage_costs, event_direct_cost
from app.services.publication_outcome import (
    CODE_LABELS,
    OUTCOME_LABELS,
    item_publication_payload,
    outcome_from_detection_run,
    pipeline_run_payload,
    summarize_detection_outcomes,
    writing_no_material_change,
)
from app.schemas import SourceCreate, SourceUpdate
from app.services.publish_service import PublishService
from app.services.source_service import SourceService
from app.services.pipeline_lock import is_write_audit_publish_busy
from app.services.pipeline_budget import claim_detection_item
from app.workers.tasks import (
    audit_event_article,
    detect_event,
    poll_source,
    publish_event_article,
    research_event,
    resolve_event_claims,
    verify_event_claims,
    write_event_article,
)

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


class LoginBody(BaseModel):
    password: str


class PublishBody(BaseModel):
    override_editorial_hold: bool = False
    target_version: int | None = None
    base_published_version: int | None = None


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
    meta = getattr(item, "metadata_json", None) or {}
    return {
        "id": str(item.id),
        "source_id": str(item.source_id),
        "url": item.url,
        "canonical_url": item.canonical_url,
        "title": item.title,
        "published_at": _iso(item.published_at),
        "detected_at": _iso(item.detected_at),
        "processing_status": item.processing_status.value,
        "has_extracted_body": has_extracted_body(item),
        "body_source": body_source_from_item(item),
        "fetch_ok": meta.get("fetch_ok") if isinstance(meta, dict) else None,
    }


def _publication_rows(db, items) -> list[dict]:
    ids = [item.id for item in items]
    latest = PipelineRunRepository(db).latest_detection_for_items(ids)
    linked = EventRepository(db).event_ids_for_items(ids)
    rows: list[dict] = []
    for item in items:
        source = getattr(item, "source", None)
        payload = item_publication_payload(
            item,
            latest_run=latest.get(item.id),
            linked_event_ids=[str(eid) for eid in linked.get(item.id, [])],
            source_name=source.name if source is not None else None,
        )
        payload["has_extracted_body"] = has_extracted_body(item)
        rows.append(payload)
    return rows


def _open_failure_out(run) -> dict:
    return {
        "id": str(run.id),
        "stage": run.stage,
        "status": run.status.value,
        "error_message": run.error_message,
        "event_id": str(run.event_id) if run.event_id else None,
        "source_item_id": str(run.source_item_id) if run.source_item_id else None,
        "started_at": _iso(run.started_at),
        "finished_at": _iso(run.finished_at),
        "attempt": run.attempt,
    }


def _claim_out(claim, editorial=None, presentation=None) -> dict:
    payload = {
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
    payload.update(editorial_public_payload(editorial))
    if presentation is not None:
        payload["presentation"] = presentation
    return payload


def _claims_out(event, db) -> list[dict]:
    _run, view = verification_view_for_event(db, event.id)
    editorials = labels_for_event_claims(list(event.claims), view)
    return [
        _claim_out(
            claim,
            editorials.get(str(claim.id)),
            public_presentation_payload(presentation_for_claim(claim, view)),
        )
        for claim in event.claims
    ]


def _article_out(article) -> dict:
    return {
        "id": str(article.id),
        "headline": article.headline,
        "summary": article.summary,
        "body": article.body,
        "body_blocks": article.body_blocks,
        "status": article.status.value,
        "current_version": article.current_version,
        "published_version": article.published_version,
        "published_at": _iso(article.published_at),
        "slug": article.slug,
        "editorial_hold": bool(article.editorial_hold),
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


def _write_audit_publish_running(db, event_id: UUID) -> bool:
    return is_write_audit_publish_busy(PipelineRunRepository(db), event_id)


def _event_out(
    event,
    *,
    pipeline_stage: str | None = None,
    pipeline_run_status: str | None = None,
    tokens_total: int | None = None,
) -> dict:
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
        "pipeline_stage": pipeline_stage,
        "pipeline_run_status": pipeline_run_status,
        "tokens_total": tokens_total,
    }


def _header_tokens(*, calls: int, total_tokens: int) -> int | None:
    if calls <= 0:
        return None
    return total_tokens


@router.post("/login")
def login(payload: LoginBody, request: Request) -> dict:
    settings = get_settings()
    if not settings.admin_password or payload.password != settings.admin_password:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Contraseña incorrecta")
    request.session["admin"] = True
    return {"ok": True}


@router.post("/logout", dependencies=[Depends(require_admin_origin)])
def logout(request: Request) -> dict:
    request.session.clear()
    return {"ok": True}


@router.get("/me", dependencies=[Depends(require_admin)])
def me() -> dict:
    return {"ok": True, "role": "admin"}


@router.get("/stats", dependencies=[Depends(require_admin)])
def stats(db: DbSession) -> dict:
    since = utc_now() - timedelta(hours=24)
    pipeline = PipelineRunRepository(db)
    usage = LlmUsageRepository(db)
    token_totals = usage.totals_since(since)
    detection_runs = pipeline.list_detection_in_range(since=since, limit=2000)
    detection_counts = pipeline.detection_counts_in_range(since=since)
    outcomes = [outcome_from_detection_run(run) for run in detection_runs]
    writing_runs = pipeline.list_stage_in_range("writing", since=since, limit=2000)
    open_fails = pipeline.open_failures()
    return {
        "monitored_sources": SourceRepository(db).count_monitored(),
        "source_items_24h": SourceItemRepository(db).count_since(since),
        "events_24h": EventRepository(db).count_since(since),
        "failed_runs_24h": pipeline.count_failed_since(since),
        "running_by_stage": pipeline.count_running_by_stage(),
        "runs_by_stage_status_24h": pipeline.count_by_stage_status_since(since),
        "items_by_status": SourceItemRepository(db).count_by_status(),
        "tokens_24h": token_totals,
        "tokens_by_role_24h": usage.totals_by_role_since(since),
        "last_failed_error": pipeline.latest_failed_error(),
        "open_failure_count": len(open_fails),
        "open_failures": [_open_failure_out(run) for run in open_fails[:20]],
        "detection_24h": {
            "timestamp_field": "coalesce(pipeline_runs.finished_at, pipeline_runs.started_at)",
            "timestamp_label": "corrida finalizada",
            **detection_counts,
            "by_outcome": summarize_detection_outcomes(outcomes),
        },
        "sources_added_24h": EventRepository(db).count_links_added_since(since),
        "no_material_change_24h": sum(1 for run in writing_runs if writing_no_material_change(run)),
        "costs_24h": aggregate_usage_costs(db, since=since),
    }


@router.get("/sources", dependencies=[Depends(require_admin)])
def list_sources(db: DbSession) -> list[dict]:
    return [_source_out(source) for source in SourceService(db).list_all()]


@router.post("/sources", dependencies=[Depends(require_admin_origin)], status_code=status.HTTP_201_CREATED)
def create_source(payload: SourceWrite, db: DbSession) -> dict:
    source = SourceService(db).create(SourceCreate(**payload.model_dump()))
    return _source_out(source)


@router.get("/sources/{source_id}", dependencies=[Depends(require_admin)])
def get_source(source_id: UUID, db: DbSession) -> dict:
    source = SourceService(db).get(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Fuente no encontrada")
    return _source_out(source)


@router.patch("/sources/{source_id}", dependencies=[Depends(require_admin_origin)])
def patch_source(source_id: UUID, payload: SourceUpdate, db: DbSession) -> dict:
    service = SourceService(db)
    source = service.get(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Fuente no encontrada")
    updated = service.update(source, payload)
    return _source_out(updated)


@router.post("/sources/{source_id}/poll", dependencies=[Depends(require_admin_origin)], status_code=status.HTTP_202_ACCEPTED)
def enqueue_poll(source_id: UUID, db: DbSession) -> dict:
    source = SourceService(db).get(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Fuente no encontrada")
    poll_source.delay(str(source_id))
    return {"queued": True, "source_id": str(source_id)}


@router.get("/source-items", dependencies=[Depends(require_admin)])
def list_items(db: DbSession, source_id: UUID | None = None, limit: int = 50) -> list[dict]:
    items, _total = SourceItemRepository(db).list_admin(source_id=source_id, limit=min(limit, 100), offset=0)
    return _publication_rows(db, items)


@router.get("/publications", dependencies=[Depends(require_admin)])
def list_publications(
    db: DbSession,
    source_id: UUID | None = None,
    unlinked: bool = False,
    outcome: str | None = None,
    code: str | None = None,
    detected_from: datetime | None = None,
    detected_to: datetime | None = None,
    published_from: datetime | None = None,
    published_to: datetime | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> dict:
    filter_outcome = bool(outcome or code)
    fetch_limit = 500 if filter_outcome else limit
    fetch_offset = 0 if filter_outcome else offset
    items, raw_total = SourceItemRepository(db).list_admin(
        source_id=source_id,
        unlinked=unlinked,
        detected_from=detected_from,
        detected_to=detected_to,
        published_from=published_from,
        published_to=published_to,
        limit=fetch_limit,
        offset=fetch_offset,
    )
    rows = _publication_rows(db, items)
    if outcome:
        rows = [row for row in rows if row.get("outcome") == outcome]
    if code:
        rows = [row for row in rows if row.get("code") == code]
    if filter_outcome:
        total = len(rows)
        page = rows[offset : offset + limit]
        truncated = raw_total > fetch_limit
    else:
        total = raw_total
        page = rows
        truncated = False
    using_published = published_from is not None or published_to is not None
    return {
        "items": page,
        "total": total,
        "offset": offset,
        "limit": limit,
        "truncated": truncated,
        "timestamp_field": "source_items.published_at" if using_published else "source_items.detected_at",
        "timestamp_label": "publicado por el medio" if using_published else "detectado en el sistema",
        "outcome_labels": OUTCOME_LABELS,
        "code_labels": CODE_LABELS,
    }


@router.get("/source-items/{item_id}", dependencies=[Depends(require_admin)])
def get_source_item(item_id: UUID, db: DbSession) -> dict:
    item = SourceItemRepository(db).get_with_source(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Publicación no encontrada")
    row = _publication_rows(db, [item])[0]
    linked = EventRepository(db).event_ids_for_items([item.id]).get(item.id, [])
    linked_ids = [str(eid) for eid in linked]
    runs = PipelineRunRepository(db).list_for_item(item.id, limit=50)
    return {
        **row,
        "pipeline_runs": [pipeline_run_payload(run, linked_event_ids=linked_ids) for run in runs],
    }


@router.get("/detection-runs", dependencies=[Depends(require_admin)])
def list_detection_runs(
    db: DbSession,
    since: datetime | None = None,
    until: datetime | None = None,
    outcome: str | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict:
    start = since or (utc_now() - timedelta(hours=24))
    pipeline = PipelineRunRepository(db)
    runs = pipeline.list_detection_in_range(since=start, until=until, limit=2000)
    counts = pipeline.detection_counts_in_range(since=start, until=until)
    item_ids = [run.source_item_id for run in runs if run.source_item_id is not None]
    linked = EventRepository(db).event_ids_for_items(item_ids)
    outcomes = []
    payloads = []
    for run in runs:
        event_ids = [str(eid) for eid in linked.get(run.source_item_id, [])] if run.source_item_id else []
        mapped = outcome_from_detection_run(run, linked_event_ids=event_ids)
        outcomes.append(mapped)
        payloads.append(pipeline_run_payload(run, linked_event_ids=event_ids))
    if outcome:
        payloads = [row for row in payloads if (row.get("detection") or {}).get("outcome") == outcome]
    return {
        "timestamp_field": "coalesce(pipeline_runs.finished_at, pipeline_runs.started_at)",
        "timestamp_label": "corrida finalizada",
        "since": start.isoformat(),
        "until": until.isoformat() if until else None,
        **counts,
        "by_outcome": summarize_detection_outcomes(outcomes),
        "runs": payloads[offset : offset + limit],
        "returned": min(len(payloads) - offset, limit) if offset < len(payloads) else 0,
        "filtered_total": len(payloads),
    }


@router.get("/costs", dependencies=[Depends(require_admin)])
def list_costs(
    db: DbSession,
    since: datetime | None = None,
    until: datetime | None = None,
) -> dict:
    start = since or (utc_now() - timedelta(hours=24))
    return aggregate_usage_costs(db, since=start, until=until)


@router.post(
    "/source-items/requeue-pending",
    dependencies=[Depends(require_admin_origin)],
    status_code=status.HTTP_202_ACCEPTED,
)
def requeue_pending_detection(
    db: DbSession,
    limit: int = Query(default=3, ge=1, le=50),
) -> dict:
    """Re-encola detección para SourceItems PENDING o FAILED hasta el tope de sucesos nuevos."""
    settings = get_settings()
    cap = int(settings.max_new_events_per_poll or 0)
    if cap > 0:
        limit = min(limit, cap)
    items = SourceItemRepository(db).list_retryable(limit=limit)
    poll_id = str(uuid4())
    for item in items:
        claim_detection_item(poll_id, str(item.id))
        detect_event.delay(str(item.id), poll_id, True)
    return {
        "queued": len(items),
        "poll_id": poll_id,
        "item_ids": [str(item.id) for item in items],
        "limit": limit,
    }


@router.get("/events", dependencies=[Depends(require_admin)])
def list_events(db: DbSession, limit: int = 50) -> list[dict]:
    events = EventRepository(db).list_recent(limit=min(limit, 100))
    event_ids = [event.id for event in events]
    latest_runs = PipelineRunRepository(db).latest_for_events(event_ids)
    token_totals = LlmUsageRepository(db).totals_for_events(event_ids)
    return [
        _event_out(
            event,
            pipeline_stage=latest_runs[event.id].stage if event.id in latest_runs else None,
            pipeline_run_status=(
                latest_runs[event.id].status.value if event.id in latest_runs else None
            ),
            tokens_total=_header_tokens(
                calls=token_totals[event.id]["calls"],
                total_tokens=token_totals[event.id]["total_tokens"],
            )
            if event.id in token_totals
            else None,
        )
        for event in events
    ]


@router.get("/events/{event_id}", dependencies=[Depends(require_admin)])
def get_event(event_id: UUID, db: DbSession) -> dict:
    event = EventRepository(db).get_with_details(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Suceso no encontrado")
    entities = {entity.id: entity for entity in EntityRepository(db).list_for_event(event_id)}
    runs = PipelineRunRepository(db).list_for_event(event_id, limit=50)
    article = ArticleRepository(db).get_by_event_id(event_id)
    live = None
    if article is not None and article.published_version is not None:
        live_row = ArticleRepository(db).get_version(article.id, article.published_version)
        if live_row is not None:
            live = {
                "headline": live_row.headline,
                "summary": live_row.summary,
                "body": live_row.body,
                "body_blocks": live_row.body_blocks,
                "version_number": live_row.version_number,
                "published_at": _iso(live_row.published_at),
            }
    usage = LlmUsageRepository(db)
    latest = runs[0] if runs else None
    token_totals = usage.totals_for_event(event_id)
    no_material = any(writing_no_material_change(run) for run in runs)
    return {
        **_event_out(
            event,
            pipeline_stage=latest.stage if latest else None,
            pipeline_run_status=latest.status.value if latest else None,
            tokens_total=_header_tokens(
                calls=token_totals["calls"],
                total_tokens=token_totals["total_tokens"],
            ),
        ),
        "country_code": event.country_code,
        "neighborhood": event.neighborhood,
        "address_text": event.address_text,
        "no_material_change": no_material,
        "cost": event_direct_cost(db, event_id),
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
        "claims": _claims_out(event, db),
        "article": _article_out(article) if article is not None else None,
        "live": live,
        "audit": _audit_out(runs),
        "token_usage": {
            **token_totals,
            "by_role_stage": usage.totals_by_role_for_event(event_id),
        },
        "pipeline_runs": [
            pipeline_run_payload(run)
            for run in runs
        ],
    }


@router.post(
    "/events/{event_id}/research",
    dependencies=[Depends(require_admin_origin)],
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
    dependencies=[Depends(require_admin_origin)],
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
    dependencies=[Depends(require_admin_origin)],
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
    dependencies=[Depends(require_admin_origin)],
    status_code=status.HTTP_202_ACCEPTED,
)
def enqueue_write(event_id: UUID, db: DbSession) -> dict:
    event = EventRepository(db).get(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Suceso no encontrado")
    running = _write_audit_publish_running(db, event_id)
    if running:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="already_running")
    write_event_article.delay(str(event_id), "admin")
    return {"queued": True, "event_id": str(event_id)}


@router.post(
    "/events/{event_id}/audit",
    dependencies=[Depends(require_admin_origin)],
    status_code=status.HTTP_202_ACCEPTED,
)
def enqueue_audit(event_id: UUID, db: DbSession) -> dict:
    event = EventRepository(db).get(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Suceso no encontrado")
    if _write_audit_publish_running(db, event_id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="already_running")
    audit_event_article.delay(str(event_id), "admin")
    return {"queued": True, "event_id": str(event_id)}


@router.post("/events/{event_id}/publish", dependencies=[Depends(require_admin_origin)])
def enqueue_publish(
    event_id: UUID,
    db: DbSession,
    payload: Annotated[PublishBody | None, Body()] = None,
) -> dict:
    payload = payload or PublishBody()
    event = EventRepository(db).get(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Suceso no encontrado")
    if _write_audit_publish_running(db, event_id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="already_running")
    article = ArticleRepository(db).get_by_event_id(event_id)
    if article is None:
        raise HTTPException(status_code=404, detail="Artículo no encontrado")
    if article.editorial_hold and payload.override_editorial_hold:
        result = PublishService(db).publish(
            event_id,
            trigger="admin_override",
            override_editorial_hold=True,
            target_version=payload.target_version,
            base_published_version=payload.base_published_version,
        )
        if not result.get("published") and result.get("reason") not in {"already_published"}:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=result.get("reason"))
        return result
    inspection = PublishService(db).inspect_publish(event_id)
    if inspection["reason"] == "already_published":
        return {"published": True, "reason": "already_published", "event_id": str(event_id)}
    if inspection["reason"] != "ready":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=inspection["reason"])
    publish_event_article.delay(str(event_id), "admin")
    return JSONResponse(
        {"queued": True, "event_id": str(event_id)},
        status_code=status.HTTP_202_ACCEPTED,
    )


@router.post("/events/{event_id}/archive", dependencies=[Depends(require_admin_origin)])
def archive_event(event_id: UUID, db: DbSession) -> dict:
    event = EventRepository(db).get(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Suceso no encontrado")
    if _write_audit_publish_running(db, event_id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="already_running")
    result = PublishService(db).archive(event_id)
    if result.get("reason") == "already_running":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="already_running")
    return result

