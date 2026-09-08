from datetime import timedelta
from uuid import UUID, uuid4

import httpx

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.services.claim_service import ClaimService
from app.services.detection_service import DetectionService
from app.services.ingestion_service import IngestionService
from app.services.pipeline_budget import (
    allow_fill_enqueue,
    allow_new_event_pipeline,
    claim_detection_item,
    release_new_event_pipeline,
)
from app.services.research_service import ResearchService
from app.services.audit_service import AuditService
from app.services.verification_service import VerificationService
from app.services.writing_service import WritingService
from app.services.publish_service import PublishService
from app.repositories import ArticleRepository
from app.workers.celery_app import celery_app

settings = get_settings()

celery_app.conf.task_routes = {
    "app.workers.tasks.poll_source": {"queue": "ingestion"},
    "app.workers.tasks.poll_monitored_sources": {"queue": "ingestion"},
    "app.workers.tasks.detect_event": {"queue": "event_detection"},
    "app.workers.tasks.research_event": {"queue": "research"},
    "app.workers.tasks.resolve_event_claims": {"queue": "claim_resolution"},
    "app.workers.tasks.verify_event_claims": {"queue": "verification"},
    "app.workers.tasks.write_event_article": {"queue": "writing"},
    "app.workers.tasks.audit_event_article": {"queue": "auditing"},
    "app.workers.tasks.publish_event_article": {"queue": "publishing"},
}
celery_app.conf.beat_schedule = {
    "poll-monitored-sources": {
        "task": "app.workers.tasks.poll_monitored_sources",
        "schedule": timedelta(seconds=settings.ingestion_poll_interval_seconds),
    }
}


def _enqueue_detection(source_item_id: UUID, poll_id: str, fill_quota: bool = False) -> None:
    detect_event.delay(str(source_item_id), poll_id, fill_quota)


def _enqueue_next_for_quota(poll_id: str, exclude_item_id: str) -> None:
    session = SessionLocal()
    try:
        from app.repositories import SourceItemRepository

        for item in SourceItemRepository(session).list_retryable(limit=20):
            if str(item.id) == exclude_item_id:
                continue
            if not claim_detection_item(poll_id, str(item.id)):
                continue
            if not allow_fill_enqueue(poll_id):
                return
            _enqueue_detection(item.id, poll_id, fill_quota=True)
            return
    finally:
        session.close()


def _item_ids_for_detection(item_ids: list[UUID]) -> list[UUID]:
    cap = int(get_settings().max_new_events_per_poll or 0)
    if cap <= 0:
        return list(item_ids)
    return list(item_ids[:cap])


@celery_app.task(name="app.workers.tasks.ping")
def ping() -> str:
    return "pong"


@celery_app.task(
    bind=True,
    name="app.workers.tasks.poll_source",
    max_retries=settings.job_max_retries,
    autoretry_for=(httpx.HTTPError, httpx.TransportError),
    retry_backoff=True,
)
def poll_source(self, source_id: str) -> dict:
    session = SessionLocal()
    poll_id = str(uuid4())
    try:
        # No encolar detección dentro del poll: el worker vería SourceItems
        # aún no commiteados → source_item_not_found.
        service = IngestionService(session)
        result = service.poll_source(UUID(source_id))
        session.commit()
        queued_ids = _item_ids_for_detection(result.item_ids)
        for item_id in queued_ids:
            _enqueue_detection(item_id, poll_id)
        return {
            "skipped": result.skipped,
            "created": result.created,
            "updated": result.updated,
            "seen": result.seen,
            "reason": result.reason,
            "item_ids": [str(item_id) for item_id in result.item_ids],
            "detection_queued": len(queued_ids),
            "poll_id": poll_id,
        }
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@celery_app.task(name="app.workers.tasks.poll_monitored_sources")
def poll_monitored_sources() -> dict:
    session = SessionLocal()
    try:
        from app.repositories import SourceRepository

        source_ids = [str(source.id) for source in SourceRepository(session).list_pollable()]
    finally:
        session.close()
    for source_id in source_ids:
        poll_source.delay(source_id)
    return {"queued": len(source_ids)}


@celery_app.task(
    bind=True,
    name="app.workers.tasks.detect_event",
    max_retries=settings.job_max_retries,
    retry_backoff=True,
)
def detect_event(
    self,
    source_item_id: str,
    poll_id: str | None = None,
    fill_quota: bool = False,
) -> dict:
    # Retries already reserved a slot on the first attempt.
    if self.request.retries == 0 and not allow_new_event_pipeline(poll_id):
        return {
            "created": False,
            "detection_skipped": True,
            "pipeline_skipped": True,
            "reason": "max_new_events_per_poll",
        }
    session = SessionLocal()
    try:
        service = DetectionService(session)
        result = service.detect(UUID(source_item_id), attempt=self.request.retries + 1)
        session.commit()
        created_new = bool(result.get("created") and result.get("event_id"))
        if created_new:
            research_event.delay(result["event_id"], "new_event")
        elif fill_quota:
            release_new_event_pipeline(poll_id)
            _enqueue_next_for_quota(poll_id, source_item_id)
        return result
    except Exception as exc:
        session.rollback()
        if _is_transient(exc):
            raise self.retry(exc=exc)
        raise
    finally:
        session.close()

@celery_app.task(
    bind=True,
    name="app.workers.tasks.research_event",
    max_retries=settings.job_max_retries,
    retry_backoff=True,
)
def research_event(self, event_id: str, trigger: str = "new_event") -> dict:
    session = SessionLocal()
    try:
        service = ResearchService(session)
        result = service.research(UUID(event_id), trigger=trigger)
        session.commit()
        if not result.get("skipped"):
            resolve_event_claims.delay(event_id, trigger)
        return result
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@celery_app.task(
    bind=True,
    name="app.workers.tasks.resolve_event_claims",
    max_retries=settings.job_max_retries,
    retry_backoff=True,
)
def resolve_event_claims(self, event_id: str, trigger: str = "research") -> dict:
    session = SessionLocal()
    try:
        service = ClaimService(session)
        result = service.resolve(UUID(event_id), trigger=trigger)
        session.commit()
        persisted = result.get("persisted")
        has_claims = persisted is None or int(persisted) > 0
        if not result.get("skipped") and has_claims:
            verify_event_claims.delay(event_id, trigger)
        return result
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@celery_app.task(
    bind=True,
    name="app.workers.tasks.verify_event_claims",
    max_retries=settings.job_max_retries,
    retry_backoff=True,
)
def verify_event_claims(self, event_id: str, trigger: str = "claims") -> dict:
    session = SessionLocal()
    try:
        service = VerificationService(session)
        result = service.verify(UUID(event_id), trigger=trigger)
        session.commit()
        if not result.get("skipped") and not result.get("error"):
            write_event_article.delay(event_id, trigger)
        return result
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@celery_app.task(
    bind=True,
    name="app.workers.tasks.write_event_article",
    max_retries=settings.job_max_retries,
    retry_backoff=True,
)
def write_event_article(self, event_id: str, trigger: str = "verification") -> dict:
    session = SessionLocal()
    try:
        service = WritingService(session)
        result = service.write(UUID(event_id), trigger=trigger)
        session.commit()
        if result.get("written") is True:
            audit_event_article.delay(event_id, trigger)
        return result
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@celery_app.task(
    bind=True,
    name="app.workers.tasks.audit_event_article",
    max_retries=settings.job_max_retries,
    retry_backoff=True,
)
def audit_event_article(self, event_id: str, trigger: str = "writing") -> dict:
    session = SessionLocal()
    try:
        service = AuditService(session)
        result = service.audit(UUID(event_id), trigger=trigger)
        session.commit()
        if result.get("skipped") is False and result.get("passed") is True:
            article = ArticleRepository(session).get_by_event_id(UUID(event_id))
            if article is None or not article.editorial_hold:
                publish_event_article.delay(event_id, trigger)
        return result
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@celery_app.task(
    bind=True,
    name="app.workers.tasks.publish_event_article",
    max_retries=settings.job_max_retries,
    retry_backoff=True,
)
def publish_event_article(self, event_id: str, trigger: str = "audit") -> dict:
    session = SessionLocal()
    try:
        service = PublishService(session)
        result = service.publish(UUID(event_id), trigger=trigger)
        session.commit()
        return result
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _is_transient(exc: BaseException) -> bool:
    name = type(exc).__name__
    text = str(exc).lower()
    return name in {"ConnectError", "TimeoutException", "ReadTimeout", "TransportError", "HTTPStatusError"} or any(
        token in text for token in ("timeout", "429", "502", "503")
    )
