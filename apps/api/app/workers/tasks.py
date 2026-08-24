from datetime import timedelta
from uuid import UUID

import httpx

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.services.claim_service import ClaimService
from app.services.detection_service import DetectionService
from app.services.ingestion_service import IngestionService
from app.services.research_service import ResearchService
from app.services.verification_service import VerificationService
from app.workers.celery_app import celery_app

settings = get_settings()

celery_app.conf.task_routes = {
    "app.workers.tasks.poll_source": {"queue": "ingestion"},
    "app.workers.tasks.poll_monitored_sources": {"queue": "ingestion"},
    "app.workers.tasks.detect_event": {"queue": "event_detection"},
    "app.workers.tasks.research_event": {"queue": "research"},
    "app.workers.tasks.resolve_event_claims": {"queue": "claim_resolution"},
    "app.workers.tasks.verify_event_claims": {"queue": "verification"},
}
celery_app.conf.beat_schedule = {
    "poll-monitored-sources": {
        "task": "app.workers.tasks.poll_monitored_sources",
        "schedule": timedelta(seconds=settings.ingestion_poll_interval_seconds),
    }
}


def _enqueue_detection(source_item_id: UUID) -> None:
    detect_event.delay(str(source_item_id))


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
    try:
        service = IngestionService(session, enqueue_detection=_enqueue_detection)
        result = service.poll_source(UUID(source_id))
        session.commit()
        return {
            "skipped": result.skipped,
            "created": result.created,
            "updated": result.updated,
            "seen": result.seen,
            "reason": result.reason,
            "item_ids": [str(item_id) for item_id in result.item_ids],
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
def detect_event(self, source_item_id: str) -> dict:
    session = SessionLocal()
    try:
        service = DetectionService(session)
        result = service.detect(UUID(source_item_id), attempt=self.request.retries + 1)
        session.commit()
        if result.get("created") and result.get("event_id"):
            research_event.delay(result["event_id"], "new_event")
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
        if not result.get("skipped"):
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
