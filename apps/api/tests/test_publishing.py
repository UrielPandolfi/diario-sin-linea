from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.article_body import plain_article_draft
from app.core.config import get_settings
from tests.origin import ADMIN_ORIGIN
from app.domain.enums import (
    ArticleStatus,
    ClaimImportance,
    ClaimStatus,
    EventStatus,
    EvidenceType,
    IngestionMethod,
    PipelineStatus,
)
from app.main import app
from app.models import Article, ArticleVersion, Claim, ClaimEvidence, PipelineRun
from app.providers.fakes import FakeStructuredLLM
from app.schemas import ArticleCreate, EventCreate, SourceCreate, SourceItemCreate
from app.schemas.auditing import ArticleAuditResult, AuditIssue, AuditIssueSeverity, AuditIssueType
from app.schemas.writing import ArticleDraft
from app.repositories import EventRepository
from app.services.article_service import ArticleService
from app.services.audit_service import AUDITING_STAGE, AuditService
from app.services.event_service import EventService
from app.services.pipeline_lock import PUBLISHING_STAGE
from app.services.publish_service import PublishService
from app.services.source_item_service import SourceItemService
from app.services.source_service import SourceService
from app.services.writing_service import WRITING_STAGE, WritingService


def _source(session: Session, **overrides):
    payload = {
        "name": "Fuente",
        "preferred_ingestion_method": IngestionMethod.RSS,
        "feed_url": "https://www.ejemplo.test/rss.xml",
        "is_monitored": True,
        "is_enabled": True,
        "domain": "ejemplo.test",
    }
    payload.update(overrides)
    return SourceService(session).create(SourceCreate(**payload))


def _item(session: Session, source_id, *, url: str, title: str, body: str, content_hash: str):
    return SourceItemService(session).ingest(
        SourceItemCreate(
            source_id=source_id,
            url=url,
            canonical_url=url,
            content_hash=content_hash,
            title=title,
            clean_text=body,
        )
    ).item


def _event(session: Session, item, **overrides):
    payload = {
        "title_internal": "Choque en Pellegrini",
        "event_type": "accidente",
        "source_item_id": item.id,
        "started_at": datetime.now(timezone.utc),
        "locality": "Rosario",
        "province": "Santa Fe",
        "short_summary": "Un colectivo chocó en Rosario",
        "relevance_score": 80,
    }
    payload.update(overrides)
    return EventService(session).create(EventCreate(**payload))


def _claim(session: Session, event, *, text: str, claim_type: str, importance: ClaimImportance, status: ClaimStatus):
    row = Claim(
        event_id=event.id,
        canonical_text=text,
        claim_type=claim_type,
        importance=importance,
        status=status,
    )
    session.add(row)
    session.flush()
    return row


def _seed_draft(session: Session, *, locality: str = "Rosario", headline: str = "Un colectivo chocó en Pellegrini"):
    source = _source(session, name=f"Fuente {locality}", domain=f"{locality.casefold()}.test", feed_url=f"https://{locality.casefold()}.test/rss.xml")
    item = _item(
        session,
        source.id,
        url=f"https://{locality.casefold()}.test/a",
        title="A",
        body="Un colectivo chocó en Pellegrini",
        content_hash=f"h-{locality}",
    )
    event = _event(session, item, locality=locality)
    claim = _claim(
        session,
        event,
        text="Un colectivo chocó en Pellegrini",
        claim_type="hecho",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.SUPPORTED,
    )
    session.add(
        ClaimEvidence(
            claim_id=claim.id,
            source_item_id=item.id,
            evidence_type=EvidenceType.SUPPORTS,
            excerpt="Un colectivo chocó en Pellegrini",
            source_url=item.url,
        )
    )
    article, _created = ArticleService(session).create_draft(
        ArticleCreate(
            event_id=event.id,
            headline=headline,
            summary="El choque ocurrió en Rosario.",
            body="Un colectivo chocó en Pellegrini.\n\nHay heridos según el draft.",
        )
    )
    session.flush()
    return event, article, claim


def _pass_audit() -> ArticleAuditResult:
    return ArticleAuditResult(passed=True, issues=[])


def _fail_audit() -> ArticleAuditResult:
    return ArticleAuditResult(
        passed=False,
        issues=[
            AuditIssue(
                type=AuditIssueType.UNSUPPORTED_CLAIM,
                severity=AuditIssueSeverity.HIGH,
                text="seis heridos",
                explanation="Esa cifra no está en el context",
                suggested_fix="Quitá la cifra",
            )
        ],
    )


def _audit_pass(session: Session, event) -> None:
    AuditService(session, llm=FakeStructuredLLM({"ArticleAuditResult": _pass_audit()})).audit(
        event.id, trigger="test"
    )


def _draft(headline: str, summary: str = "s", body: str = "b") -> ArticleDraft:
    return plain_article_draft(headline, summary, body)


def _publish(session: Session, event):
    return PublishService(session).publish(event.id, trigger="test")


def test_draft_and_cap_exhausted_are_not_published(db_session: Session) -> None:
    event, article, _claim_row = _seed_draft(db_session)
    assert article.published_version is None
    fail = FakeStructuredLLM(
        {
            "ArticleAuditResult": [_fail_audit(), _fail_audit(), _fail_audit()],
            "ArticleDraft": [
                _draft("Uno"),
                _draft("Dos"),
            ],
        }
    )
    result = AuditService(db_session, llm=fail, writer=fail).audit(event.id, trigger="test")
    db_session.refresh(article)
    db_session.refresh(event)
    published = _publish(db_session, event)
    db_session.refresh(article)
    assert result["cap_exhausted"] is True
    assert result["passed"] is False
    assert article.status == ArticleStatus.DRAFT
    assert published["published"] is False
    assert published["reason"] == "audit_not_passed"
    assert event.status == EventStatus.DETECTED
    assert article.published_at is None


def test_passed_audit_can_publish_event_and_article(db_session: Session) -> None:
    event, article, _claim_row = _seed_draft(db_session)
    original_event_status = event.status
    _audit_pass(db_session, event)
    db_session.refresh(article)
    assert article.status == ArticleStatus.DRAFT
    result = _publish(db_session, event)
    db_session.refresh(article)
    db_session.refresh(event)
    assert result["published"] is True
    assert result["reason"] == "published"
    assert article.status == ArticleStatus.PUBLISHED
    assert article.published_at is not None
    assert article.published_version == article.current_version
    assert event.status == EventStatus.PUBLISHED
    assert event.slug == article.slug
    assert original_event_status == EventStatus.DETECTED
    again = _publish(db_session, event)
    assert again["reason"] == "already_published"
    assert again["published"] is True


def test_auto_publish_flag_does_not_gate_passed_chain(monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "auto_publish", False)
    queued: list[tuple] = []

    class Sess:
        def commit(self) -> None:
            pass

        def rollback(self) -> None:
            pass

        def close(self) -> None:
            pass

    monkeypatch.setattr("app.workers.tasks.SessionLocal", Sess)
    monkeypatch.setattr("app.workers.tasks.publish_event_article.delay", lambda *args: queued.append(args))
    from app.workers.tasks import audit_event_article
    from types import SimpleNamespace

    monkeypatch.setattr(
        "app.workers.tasks.ArticleRepository",
        lambda session: SimpleNamespace(get_by_event_id=lambda *_a, **_k: SimpleNamespace(editorial_hold=False)),
    )
    monkeypatch.setattr(
        "app.workers.tasks.AuditService",
        lambda session: SimpleNamespace(audit=lambda *_a, **_k: {"skipped": False, "passed": True}),
    )
    audit_event_article.run("00000000-0000-0000-0000-000000000001", "writing")
    assert queued == [("00000000-0000-0000-0000-000000000001", "writing")]
    assert settings.auto_publish is False


def test_published_update_keeps_live_until_passed_audit(db_session: Session) -> None:
    event, article, claim = _seed_draft(db_session, headline="Titular publicado")
    llm = FakeStructuredLLM(
        {"ArticleDraft": _draft("Titular publicado", "Resumen", "Cuerpo live")}
    )
    WritingService(db_session, llm=llm).write(event.id, trigger="test")
    _audit_pass(db_session, event)
    _publish(db_session, event)
    db_session.refresh(article)
    live_version = article.published_version
    live_headline = article.headline
    published_at = article.published_at

    second = WritingService(db_session, llm=llm).write(event.id, trigger="test")
    db_session.refresh(article)
    assert second["reason"] == "no_material_change"
    assert article.status == ArticleStatus.PUBLISHED
    assert article.published_version == live_version

    extra = _claim(
        db_session,
        event,
        text="El choque dejó seis heridos",
        claim_type="hecho",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.SUPPORTED,
    )
    detailed = EventRepository(db_session).get_with_details(event.id)
    assert detailed is not None
    session_item = detailed.event_sources[0].source_item
    db_session.add(
        ClaimEvidence(
            claim_id=extra.id,
            source_item_id=session_item.id,
            evidence_type=EvidenceType.SUPPORTS,
            excerpt="Un colectivo chocó en Pellegrini",
            source_url=session_item.url,
        )
    )
    db_session.flush()
    update_llm = FakeStructuredLLM(
        {"ArticleDraft": _draft("Nuevo titular con heridos", "s", "cuerpo nuevo")}
    )
    written = WritingService(db_session, llm=update_llm).write(event.id, trigger="test")
    db_session.refresh(article)
    db_session.refresh(event)
    assert written["written"] is True
    assert article.status == ArticleStatus.DRAFT
    assert article.published_version == live_version
    assert article.published_at == published_at
    assert article.headline == "Nuevo titular con heridos"
    assert event.status == EventStatus.PUBLISHED

    live = db_session.scalars(
        select(ArticleVersion).where(
            ArticleVersion.article_id == article.id,
            ArticleVersion.version_number == live_version,
        )
    ).one()
    assert live.headline == live_headline

    cap = FakeStructuredLLM(
        {
            "ArticleAuditResult": [_fail_audit(), _fail_audit(), _fail_audit()],
            "ArticleDraft": [
                _draft("Cap 1"),
                _draft("Cap 2"),
            ],
        }
    )
    exhausted = AuditService(db_session, llm=cap, writer=cap).audit(event.id, trigger="test")
    blocked = _publish(db_session, event)
    db_session.refresh(article)
    assert exhausted["cap_exhausted"] is True
    assert blocked["reason"] == "audit_not_passed"
    assert article.published_version == live_version
    assert article.status == ArticleStatus.DRAFT

    _audit_pass(db_session, event)
    promoted = _publish(db_session, event)
    db_session.refresh(article)
    db_session.refresh(event)
    assert promoted["published"] is True
    assert article.status == ArticleStatus.PUBLISHED
    assert article.published_version == article.current_version
    assert article.published_at == published_at
    assert event.last_material_update_at is not None
    assert event.status == EventStatus.PUBLISHED


def test_publish_blocked_when_writing_running(db_session: Session) -> None:
    event, _article, _claim_row = _seed_draft(db_session)
    _audit_pass(db_session, event)
    db_session.add(PipelineRun(event_id=event.id, stage=WRITING_STAGE, status=PipelineStatus.RUNNING, metadata_json={}))
    db_session.flush()
    result = _publish(db_session, event)
    assert result["skipped"] is True
    assert result["reason"] == "already_running"


def test_write_blocked_when_publishing_running(db_session: Session) -> None:
    event, _article, _claim_row = _seed_draft(db_session)
    db_session.add(
        PipelineRun(event_id=event.id, stage=PUBLISHING_STAGE, status=PipelineStatus.RUNNING, metadata_json={})
    )
    db_session.flush()
    llm = FakeStructuredLLM(
        {"ArticleDraft": _draft("H")}
    )
    result = WritingService(db_session, llm=llm).write(event.id, trigger="test")
    assert result["skipped"] is True
    assert result["reason"] == "already_running"
    assert llm.calls == []


def test_integrity_error_when_precheck_misses_publishing_running(db_session: Session, monkeypatch) -> None:
    event, _article, _claim_row = _seed_draft(db_session)
    db_session.add(
        PipelineRun(event_id=event.id, stage=PUBLISHING_STAGE, status=PipelineStatus.RUNNING, metadata_json={})
    )
    db_session.flush()
    service = PublishService(db_session)
    monkeypatch.setattr(service.pipeline, "get_running", lambda *_a, **_k: None)
    result = service.publish(event.id, trigger="test")
    assert result["skipped"] is True
    assert result["reason"] == "already_running"


def test_admin_publish_retry_and_conflict(db_session: Session, monkeypatch) -> None:
    queued: list[tuple] = []
    monkeypatch.setattr("app.api.admin.publish_event_article.delay", lambda *args: queued.append(args))
    event, _article, _claim_row = _seed_draft(db_session)
    db_session.commit()
    settings = get_settings()
    with TestClient(app) as client:
        client.post("/api/v1/admin/login", json={"password": settings.admin_password})
        denied = client.post(f"/api/v1/admin/events/{event.id}/publish", headers=ADMIN_ORIGIN)
        assert denied.status_code == 409
        assert denied.json()["detail"] == "audit_not_passed"
        assert queued == []

        _audit_pass(db_session, event)
        accepted = client.post(f"/api/v1/admin/events/{event.id}/publish", headers=ADMIN_ORIGIN)
        assert accepted.status_code == 202
        assert queued == [(str(event.id), "admin")]

        _publish(db_session, event)
        db_session.commit()
        again = client.post(f"/api/v1/admin/events/{event.id}/publish", headers=ADMIN_ORIGIN)
        assert again.status_code == 200
        assert again.json()["reason"] == "already_published"

        db_session.add(
            PipelineRun(event_id=event.id, stage=AUDITING_STAGE, status=PipelineStatus.RUNNING, metadata_json={})
        )
        db_session.commit()
        busy = client.post(f"/api/v1/admin/events/{event.id}/write", headers=ADMIN_ORIGIN)
        assert busy.status_code == 409


def test_archive_hides_from_public_predicate(db_session: Session) -> None:
    event, article, _claim_row = _seed_draft(db_session)
    _audit_pass(db_session, event)
    _publish(db_session, event)
    result = PublishService(db_session).archive(event.id)
    db_session.refresh(article)
    db_session.refresh(event)
    assert result["archived"] is True
    assert article.status == ArticleStatus.ARCHIVED
    assert event.status == EventStatus.ARCHIVED
    count = db_session.scalar(select(func.count()).select_from(Article).where(Article.event_id == event.id))
    assert count == 1
