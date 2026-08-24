from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
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
from app.providers.base import ProviderNotConfiguredError
from app.providers.fakes import FakeStructuredLLM
from app.providers.registry import ModelRole, get_structured_provider
from app.schemas import ArticleCreate, EventCreate, SourceCreate, SourceItemCreate
from app.schemas.auditing import ArticleAuditResult, AuditIssue, AuditIssueSeverity, AuditIssueType
from app.schemas.writing import ArticleDraft
from app.services.article_service import ArticleService
from app.services.audit_service import AUDITING_STAGE, AuditService
from app.services.event_service import EventService
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


def _item(
    session: Session,
    source_id,
    *,
    url: str,
    title: str,
    body: str,
    content_hash: str,
    raw_text: str | None = None,
):
    return SourceItemService(session).ingest(
        SourceItemCreate(
            source_id=source_id,
            url=url,
            canonical_url=url,
            content_hash=content_hash,
            title=title,
            clean_text=body,
            raw_text=raw_text,
            excerpt=body[:80],
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


def _draft(**overrides) -> ArticleDraft:
    payload = {
        "headline": "Un colectivo chocó en avenida Pellegrini",
        "summary": "El choque ocurrió esta tarde en Rosario.",
        "body": "Un colectivo chocó en avenida Pellegrini.\n\nLas fuentes listadas coinciden en el lugar.",
    }
    payload.update(overrides)
    return ArticleDraft(**payload)


def _pass_audit() -> ArticleAuditResult:
    return ArticleAuditResult(passed=True, issues=[])


def _fail_audit(**overrides) -> ArticleAuditResult:
    payload = {
        "passed": False,
        "issues": [
            AuditIssue(
                type=AuditIssueType.UNSUPPORTED_CLAIM,
                severity=AuditIssueSeverity.HIGH,
                text="seis heridos",
                explanation="Esa cifra no está en el context",
                suggested_fix="Quitá la cifra no respaldada",
            )
        ],
    }
    payload.update(overrides)
    return ArticleAuditResult(**payload)


def _seed_draft(session: Session, *, raw_text: str | None = None, headline: str = "Un colectivo chocó en Pellegrini"):
    source = _source(session)
    item = _item(
        session,
        source.id,
        url="https://ejemplo.test/a",
        title="A",
        body="Un colectivo chocó en Pellegrini",
        content_hash="h1",
        raw_text=raw_text,
    )
    event = _event(session, item)
    event.status = EventStatus.DETECTED
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
    return event, article


def _service(session: Session, llm: FakeStructuredLLM) -> AuditService:
    return AuditService(session, llm=llm, writer=llm)


def test_audit_prompt_has_context_and_draft_not_html(db_session: Session) -> None:
    html = "<html><body><article>SECRETO raw_text no debe ir al prompt</article></body></html>"
    event, article = _seed_draft(db_session, raw_text=html)
    llm = FakeStructuredLLM({"ArticleAuditResult": _pass_audit()})
    result = _service(db_session, llm).audit(event.id, trigger="admin")
    prompt = llm.user_prompts[0]
    assert result["passed"] is True
    assert article.headline in prompt
    assert "Un colectivo chocó en Pellegrini" in prompt
    assert "confirmed_claims" in prompt
    assert html not in prompt
    assert "raw_text" not in prompt
    assert "SECRETO" not in prompt
    assert "ANTHROPIC_API_KEY" not in prompt
    assert "DETECTED" not in prompt
    assert llm.calls == ["ArticleAuditResult"]


def test_passed_audit_marks_ready_without_rewrite(db_session: Session) -> None:
    event, article = _seed_draft(db_session)
    event_status = event.status
    version = article.current_version
    llm = FakeStructuredLLM({"ArticleAuditResult": _pass_audit(), "ArticleDraft": _draft()})
    result = _service(db_session, llm).audit(event.id, trigger="admin")
    db_session.refresh(event)
    db_session.refresh(article)
    assert result["skipped"] is False
    assert result["passed"] is True
    assert result["rewrite_count"] == 0
    assert result["audit_count"] == 1
    assert result["cap_exhausted"] is False
    assert result["reason"] == "passed"
    assert article.status == ArticleStatus.READY_FOR_REVIEW
    assert article.current_version == version
    assert event.status == event_status == EventStatus.DETECTED
    assert llm.calls == ["ArticleAuditResult"]
    versions = db_session.scalar(
        select(func.count()).select_from(ArticleVersion).where(ArticleVersion.article_id == article.id)
    )
    assert versions == 1


def test_fail_rewrite_respects_cap(db_session: Session) -> None:
    event, article = _seed_draft(db_session)
    llm = FakeStructuredLLM(
        {
            "ArticleAuditResult": [_fail_audit(), _fail_audit(), _fail_audit()],
            "ArticleDraft": [
                _draft(headline="Corrección uno"),
                _draft(headline="Corrección dos"),
            ],
        }
    )
    result = _service(db_session, llm).audit(event.id, trigger="admin")
    db_session.refresh(event)
    db_session.refresh(article)
    count = db_session.scalar(select(func.count()).select_from(Article).where(Article.event_id == event.id))
    versions = list(
        db_session.scalars(
            select(ArticleVersion)
            .where(ArticleVersion.article_id == article.id)
            .order_by(ArticleVersion.version_number)
        )
    )
    assert result["passed"] is False
    assert result["cap_exhausted"] is True
    assert result["rewrite_count"] == 2
    assert result["audit_count"] == 3
    assert result["reason"] == "cap_exhausted"
    assert article.status == ArticleStatus.READY_FOR_REVIEW
    assert article.current_version == 3
    assert article.headline == "Corrección dos"
    assert event.status == EventStatus.DETECTED
    assert count == 1
    assert [row.change_reason for row in versions] == ["initial", "audit_rewrite", "audit_rewrite"]
    assert llm.calls.count("ArticleAuditResult") == 3
    assert llm.calls.count("ArticleDraft") == 2
    assert result["issues"]


def test_rewrite_persists_when_next_sol_fails_then_retry_does_not_duplicate(db_session: Session) -> None:
    event, article = _seed_draft(db_session)
    article_id = article.id
    llm = FakeStructuredLLM(
        {
            "ArticleAuditResult": [_fail_audit(), RuntimeError("sol boom")],
            "ArticleDraft": [_draft(headline="Draft corregido")],
        }
    )
    result = _service(db_session, llm).audit(event.id, trigger="admin")
    db_session.refresh(article)
    db_session.refresh(event)
    run = db_session.scalars(
        select(PipelineRun)
        .where(PipelineRun.event_id == event.id, PipelineRun.stage == AUDITING_STAGE)
        .order_by(PipelineRun.started_at.desc())
    ).first()
    assert result["error"]
    assert run is not None
    assert run.status == PipelineStatus.FAILED
    assert article.status == ArticleStatus.DRAFT
    assert article.current_version == 2
    assert article.headline == "Draft corregido"
    assert event.status == EventStatus.DETECTED

    retry_llm = FakeStructuredLLM({"ArticleAuditResult": _pass_audit()})
    retry = _service(db_session, retry_llm).audit(event.id, trigger="admin")
    db_session.refresh(article)
    count = db_session.scalar(select(func.count()).select_from(Article).where(Article.event_id == event.id))
    assert retry["passed"] is True
    assert retry["rewrite_count"] == 0
    assert article.id == article_id
    assert article.status == ArticleStatus.READY_FOR_REVIEW
    assert count == 1
    assert retry_llm.calls == ["ArticleAuditResult"]


def test_article_not_draft_skips_llm(db_session: Session) -> None:
    event, article = _seed_draft(db_session)
    article.status = ArticleStatus.PUBLISHED
    db_session.flush()
    llm = FakeStructuredLLM({"ArticleAuditResult": _pass_audit()})
    result = _service(db_session, llm).audit(event.id, trigger="admin")
    db_session.refresh(article)
    assert result["reason"] == "article_not_draft"
    assert result["audited"] is False
    assert result["skipped"] is False
    assert llm.calls == []
    assert article.status == ArticleStatus.PUBLISHED


def test_no_article_skips_llm(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(db_session, source.id, url="https://ejemplo.test/a", title="A", body="Choque", content_hash="h1")
    event = _event(db_session, item)
    llm = FakeStructuredLLM({"ArticleAuditResult": _pass_audit()})
    result = _service(db_session, llm).audit(event.id, trigger="admin")
    assert result["reason"] == "no_article"
    assert result["audited"] is False
    assert llm.calls == []


def test_running_lock_skips_llm(db_session: Session) -> None:
    event, _article = _seed_draft(db_session)
    db_session.add(
        PipelineRun(event_id=event.id, stage=AUDITING_STAGE, status=PipelineStatus.RUNNING, metadata_json={})
    )
    db_session.flush()
    llm = FakeStructuredLLM({"ArticleAuditResult": _pass_audit()})
    result = _service(db_session, llm).audit(event.id, trigger="admin")
    assert result["skipped"] is True
    assert result["reason"] == "already_running"
    assert llm.calls == []


def test_audit_skips_when_writing_running(db_session: Session) -> None:
    event, _article = _seed_draft(db_session)
    db_session.add(PipelineRun(event_id=event.id, stage=WRITING_STAGE, status=PipelineStatus.RUNNING, metadata_json={}))
    db_session.flush()
    llm = FakeStructuredLLM({"ArticleAuditResult": _pass_audit()})
    result = _service(db_session, llm).audit(event.id, trigger="admin")
    assert result["skipped"] is True
    assert result["reason"] == "already_running"
    assert llm.calls == []


def test_write_skips_when_auditing_running(db_session: Session) -> None:
    event, _article = _seed_draft(db_session)
    db_session.add(
        PipelineRun(event_id=event.id, stage=AUDITING_STAGE, status=PipelineStatus.RUNNING, metadata_json={})
    )
    db_session.flush()
    llm = FakeStructuredLLM({"ArticleDraft": _draft()})
    result = WritingService(db_session, llm=llm).write(event.id, trigger="admin")
    assert result["skipped"] is True
    assert result["reason"] == "already_running"
    assert llm.calls == []


def test_integrity_error_when_precheck_misses_opposite_running(db_session: Session, monkeypatch) -> None:
    event, _article = _seed_draft(db_session)
    db_session.add(PipelineRun(event_id=event.id, stage=WRITING_STAGE, status=PipelineStatus.RUNNING, metadata_json={}))
    db_session.flush()
    llm = FakeStructuredLLM({"ArticleAuditResult": _pass_audit()})
    service = _service(db_session, llm)
    monkeypatch.setattr(service.pipeline, "get_running", lambda *_a, **_k: None)
    result = service.audit(event.id, trigger="admin")
    assert result["skipped"] is True
    assert result["reason"] == "already_running"
    assert llm.calls == []


def test_admin_audit_accepted_and_get_compact(db_session: Session, monkeypatch) -> None:
    queued: list[tuple] = []
    monkeypatch.setattr("app.api.admin.audit_event_article.delay", lambda *args: queued.append(args))
    event, _article = _seed_draft(db_session)
    llm = FakeStructuredLLM({"ArticleAuditResult": _pass_audit()})
    _service(db_session, llm).audit(event.id, trigger="admin")
    settings = get_settings()
    with TestClient(app) as client:
        login = client.post("/api/v1/admin/login", json={"password": settings.admin_password})
        assert login.status_code == 200
        detail = client.get(f"/api/v1/admin/events/{event.id}")
        response = client.post(f"/api/v1/admin/events/{event.id}/audit")
    assert detail.status_code == 200
    body = detail.json()
    assert body["article"]["status"] == ArticleStatus.READY_FOR_REVIEW.value
    assert body["audit"]["passed"] is True
    assert body["audit"]["cap_exhausted"] is False
    assert body["status"] == EventStatus.DETECTED.value
    assert response.status_code == 202
    assert queued == [(str(event.id), "admin")]


def test_admin_audit_conflict_when_writing_running(db_session: Session, monkeypatch) -> None:
    queued: list[tuple] = []
    monkeypatch.setattr("app.api.admin.audit_event_article.delay", lambda *args: queued.append(args))
    event, _article = _seed_draft(db_session)
    db_session.add(PipelineRun(event_id=event.id, stage=WRITING_STAGE, status=PipelineStatus.RUNNING, metadata_json={}))
    db_session.commit()
    settings = get_settings()
    with TestClient(app) as client:
        client.post("/api/v1/admin/login", json={"password": settings.admin_password})
        response = client.post(f"/api/v1/admin/events/{event.id}/audit")
    assert response.status_code == 409
    assert queued == []


def test_admin_write_conflict_when_auditing_running(db_session: Session, monkeypatch) -> None:
    queued: list[tuple] = []
    monkeypatch.setattr("app.api.admin.write_event_article.delay", lambda *args: queued.append(args))
    event, _article = _seed_draft(db_session)
    db_session.add(
        PipelineRun(event_id=event.id, stage=AUDITING_STAGE, status=PipelineStatus.RUNNING, metadata_json={})
    )
    db_session.commit()
    settings = get_settings()
    with TestClient(app) as client:
        client.post("/api/v1/admin/login", json={"password": settings.admin_password})
        response = client.post(f"/api/v1/admin/events/{event.id}/write")
    assert response.status_code == 409
    assert queued == []


def test_write_enqueues_audit_only_when_written(monkeypatch) -> None:
    queued: list[tuple] = []

    class Sess:
        def commit(self) -> None:
            pass

        def rollback(self) -> None:
            pass

        def close(self) -> None:
            pass

    monkeypatch.setattr("app.workers.tasks.SessionLocal", Sess)
    monkeypatch.setattr("app.workers.tasks.audit_event_article.delay", lambda *args: queued.append(args))
    from app.workers.tasks import write_event_article

    monkeypatch.setattr(
        "app.workers.tasks.WritingService",
        lambda session: SimpleNamespace(write=lambda *_a, **_k: {"skipped": False, "written": True, "event_id": "eid"}),
    )
    write_event_article.run("00000000-0000-0000-0000-000000000001", "verification")
    assert queued == [("00000000-0000-0000-0000-000000000001", "verification")]

    queued.clear()
    monkeypatch.setattr(
        "app.workers.tasks.WritingService",
        lambda session: SimpleNamespace(
            write=lambda *_a, **_k: {"skipped": False, "written": False, "error": "boom"}
        ),
    )
    write_event_article.run("00000000-0000-0000-0000-000000000001", "verification")
    assert queued == []

    monkeypatch.setattr(
        "app.workers.tasks.WritingService",
        lambda session: SimpleNamespace(
            write=lambda *_a, **_k: {"skipped": True, "written": False, "reason": "already_running"}
        ),
    )
    write_event_article.run("00000000-0000-0000-0000-000000000001", "admin")
    assert queued == []

    monkeypatch.setattr(
        "app.workers.tasks.WritingService",
        lambda session: SimpleNamespace(
            write=lambda *_a, **_k: {"skipped": False, "written": False, "reason": "no_claims"}
        ),
    )
    write_event_article.run("00000000-0000-0000-0000-000000000001", "admin")
    assert queued == []

    monkeypatch.setattr(
        "app.workers.tasks.WritingService",
        lambda session: SimpleNamespace(
            write=lambda *_a, **_k: {"skipped": False, "written": False, "reason": "no_material_change"}
        ),
    )
    write_event_article.run("00000000-0000-0000-0000-000000000001", "admin")
    assert queued == []


def test_auditing_rejects_anthropic(monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "auditing_provider", "anthropic")
    monkeypatch.setattr(settings, "auditing_model", "claude-test")
    with pytest.raises(ProviderNotConfiguredError, match="no es un proveedor de auditoría"):
        get_structured_provider(ModelRole.AUDITING)


def test_ready_for_review_second_audit_does_not_create_article(db_session: Session) -> None:
    event, article = _seed_draft(db_session)
    llm = FakeStructuredLLM({"ArticleAuditResult": _pass_audit()})
    _service(db_session, llm).audit(event.id, trigger="admin")
    db_session.refresh(article)
    second = FakeStructuredLLM({"ArticleAuditResult": _pass_audit()})
    result = _service(db_session, second).audit(event.id, trigger="admin")
    count = db_session.scalar(select(func.count()).select_from(Article).where(Article.event_id == event.id))
    assert result["reason"] == "article_not_draft"
    assert second.calls == []
    assert count == 1
    assert article.id
