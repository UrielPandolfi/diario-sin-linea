from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from openai import RateLimitError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.article_body import annotated_article_draft, plain_article_draft
from app.core.config import get_settings
from app.core.prompts import load_prompt
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
from app.providers.base import ProviderNotConfiguredError
from app.providers.fakes import FakeStructuredLLM
from app.providers.openai_provider import OpenAIStructuredProvider
from app.providers.registry import ModelRole, get_structured_provider
from app.schemas import ArticleCreate, EventCreate, SourceCreate, SourceItemCreate
from app.schemas.auditing import ArticleAuditResult, AuditIssue, AuditIssueSeverity, AuditIssueType
from app.schemas.writing import ArticleDraft
from app.services.article_service import ArticleService
from app.services.audit_service import AUDITING_STAGE, AuditService, normalize_audit_result
from app.services.event_service import EventService
from app.services.publish_service import PublishService
from app.services.source_item_service import SourceItemService
from app.services.source_service import SourceService
from app.services.writing_service import WRITING_STAGE, WritingService
from tests.editorial_snapshot import persist_version_snapshot


def test_normalize_audit_result_low_issues_do_not_block() -> None:
    low_only = ArticleAuditResult(
        passed=False,
        issues=[
            AuditIssue(
                type=AuditIssueType.FRAMING,
                severity=AuditIssueSeverity.LOW,
                text="tono",
                explanation="nitpick",
                suggested_fix=None,
            )
        ],
    )
    normalized = normalize_audit_result(low_only)
    assert normalized.passed is True
    assert len(normalized.issues) == 1

    medium = ArticleAuditResult(
        passed=True,
        issues=[
            AuditIssue(
                type=AuditIssueType.ATTRIBUTION,
                severity=AuditIssueSeverity.MEDIUM,
                text="dato",
                explanation="falta atribución",
                suggested_fix="atribuí",
            )
        ],
    )
    assert normalize_audit_result(medium).passed is False

    redundancy = ArticleAuditResult(
        passed=True,
        issues=[
            AuditIssue(
                type=AuditIssueType.REDUNDANCY,
                severity=AuditIssueSeverity.MEDIUM,
                text="summary",
                explanation="summary y primer párrafo son el mismo texto",
                suggested_fix="avanzá el lead",
            )
        ],
    )
    assert normalize_audit_result(redundancy).passed is False
    assert AuditIssueType.CLARITY.value == "CLARITY"


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
    body = overrides.pop(
        "body",
        "Un colectivo chocó en avenida Pellegrini.\n\nLas fuentes listadas coinciden en el lugar.",
    )
    headline = overrides.pop("headline", "Un colectivo chocó en avenida Pellegrini")
    summary = overrides.pop("summary", "El choque ocurrió esta tarde en Rosario.")
    draft = plain_article_draft(headline, summary, body)
    return draft.model_copy(update=overrides) if overrides else draft


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
    persist_version_snapshot(session, event, article)
    return event, article


def _service(session: Session, llm: FakeStructuredLLM) -> AuditService:
    return AuditService(session, llm=llm, writer=llm)


def test_audit_low_only_passes_without_rewrite(db_session: Session) -> None:
    event, article = _seed_draft(db_session)
    version = article.current_version
    llm = FakeStructuredLLM(
        {
            "ArticleAuditResult": ArticleAuditResult(
                passed=False,
                issues=[
                    AuditIssue(
                        type=AuditIssueType.ADJECTIVE,
                        severity=AuditIssueSeverity.LOW,
                        text="breve",
                        explanation="estilo menor",
                        suggested_fix=None,
                    )
                ],
            ),
            "ArticleDraft": _draft(),
        }
    )
    result = _service(db_session, llm).audit(event.id, trigger="admin")
    assert result["passed"] is True
    assert result["reason"] == "passed"
    assert result["rewrite_count"] == 0
    assert result["audit_count"] == 1
    assert article.current_version == version
    assert llm.calls == ["ArticleAuditResult"]


def test_audit_payload_is_language_only(db_session: Session) -> None:
    html = "<html><body><article>SECRETO raw_text no debe ir al prompt</article></body></html>"
    event, article = _seed_draft(db_session, raw_text=html)
    llm = FakeStructuredLLM({"ArticleAuditResult": _pass_audit()})
    result = _service(db_session, llm).audit(event.id, trigger="admin")
    prompt = llm.user_prompts[0]
    dumped = prompt.casefold()
    assert result["passed"] is True
    assert article.headline in prompt
    assert article.summary in prompt
    assert "Un colectivo chocó en Pellegrini" in prompt
    assert "body_blocks" in prompt
    assert html not in prompt
    assert "raw_text" not in prompt
    assert "SECRETO" not in prompt
    assert "ANTHROPIC_API_KEY" not in prompt
    assert "DETECTED" not in prompt
    for forbidden in (
        "confirmed_claims",
        "evidence_snapshot",
        "structural_findings",
        "heuristic_signals",
        "decision_by_claim_id",
        "articlecontext",
        "coverage_gap",
        "support_basis",
        "central_unverified",
    ):
        assert forbidden not in dumped
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
    assert article.status == ArticleStatus.DRAFT
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
    assert article.status == ArticleStatus.DRAFT
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
    assert article.status == ArticleStatus.DRAFT
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
        response = client.post(f"/api/v1/admin/events/{event.id}/audit", headers=ADMIN_ORIGIN)
    assert detail.status_code == 200
    body = detail.json()
    assert body["article"]["status"] == ArticleStatus.DRAFT.value
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
        response = client.post(f"/api/v1/admin/events/{event.id}/audit", headers=ADMIN_ORIGIN)
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
        response = client.post(f"/api/v1/admin/events/{event.id}/write", headers=ADMIN_ORIGIN)
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


def test_audit_enqueues_publish_only_when_passed(monkeypatch) -> None:
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

    monkeypatch.setattr(
        "app.workers.tasks.ArticleRepository",
        lambda session: SimpleNamespace(get_by_event_id=lambda *_a, **_k: SimpleNamespace(editorial_hold=False)),
    )

    monkeypatch.setattr(
        "app.workers.tasks.AuditService",
        lambda session: SimpleNamespace(
            audit=lambda *_a, **_k: {"skipped": False, "passed": True, "event_id": "eid"}
        ),
    )
    audit_event_article.run("00000000-0000-0000-0000-000000000001", "writing")
    assert queued == [("00000000-0000-0000-0000-000000000001", "writing")]

    queued.clear()
    monkeypatch.setattr(
        "app.workers.tasks.AuditService",
        lambda session: SimpleNamespace(
            audit=lambda *_a, **_k: {
                "skipped": False,
                "passed": False,
                "reason": "cap_exhausted",
                "event_id": "eid",
            }
        ),
    )
    audit_event_article.run("00000000-0000-0000-0000-000000000001", "writing")
    assert queued == []

    monkeypatch.setattr(
        "app.workers.tasks.AuditService",
        lambda session: SimpleNamespace(
            audit=lambda *_a, **_k: {"skipped": True, "passed": True, "reason": "already_running"}
        ),
    )
    audit_event_article.run("00000000-0000-0000-0000-000000000001", "admin")
    assert queued == []

    queued.clear()
    monkeypatch.setattr(
        "app.workers.tasks.ArticleRepository",
        lambda session: SimpleNamespace(get_by_event_id=lambda *_a, **_k: SimpleNamespace(editorial_hold=True)),
    )
    monkeypatch.setattr(
        "app.workers.tasks.AuditService",
        lambda session: SimpleNamespace(
            audit=lambda *_a, **_k: {"skipped": False, "passed": True, "event_id": "eid"}
        ),
    )
    audit_event_article.run("00000000-0000-0000-0000-000000000001", "writing")
    assert queued == []


def test_auditing_rejects_anthropic(monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "auditing_provider", "anthropic")
    monkeypatch.setattr(settings, "auditing_model", "claude-test")
    with pytest.raises(ProviderNotConfiguredError, match="no es un proveedor de auditoría"):
        get_structured_provider(ModelRole.AUDITING)


def test_published_second_audit_does_not_create_article(db_session: Session) -> None:
    event, article = _seed_draft(db_session)
    llm = FakeStructuredLLM({"ArticleAuditResult": _pass_audit()})
    _service(db_session, llm).audit(event.id, trigger="admin")
    published = PublishService(db_session).publish(event.id, trigger="test")
    assert published["published"] is True
    db_session.refresh(article)
    second = FakeStructuredLLM({"ArticleAuditResult": _pass_audit()})
    result = _service(db_session, second).audit(event.id, trigger="admin")
    count = db_session.scalar(select(func.count()).select_from(Article).where(Article.event_id == event.id))
    assert result["reason"] == "article_not_draft"
    assert second.calls == []
    assert count == 1
    assert article.status == ArticleStatus.PUBLISHED
    assert article.id


def test_audit_prompt_covers_language_bias_not_verification() -> None:
    prompt = load_prompt("article_audit.md")
    folded = prompt.casefold()
    assert "UNATTRIBUTED_CHARACTERIZATION" in prompt
    assert "voz de Sin Línea" in prompt or "voz de sin línea" in folded
    assert "citas y declaraciones claramente atribuidas" in folded
    assert "no las neutralices" in folded
    assert "no verifiques hechos" in folded
    assert "no apliques una lista ciega" in folded
    assert "una muerte" in folded and "condena" in folded
    assert "supported no significa" not in folded
    assert "coverage_gap" not in folded
    assert "decision_by_claim_id" not in folded
    assert "si el draft lo afirma como hecho de sin línea, reportá attribution" not in folded
    assert "$98,08 millones" not in prompt
    assert "Nunca uses un type OTHER" in prompt
    assert "NUMBER" in prompt and "No uses NUMBER" in prompt


def test_writing_prompt_covers_characterization_and_causality() -> None:
    prompt = load_prompt("article_writing.md")
    assert "Caracterizaciones no son hechos por consenso" in prompt
    assert "Fue la mayor crisis diplomática entre ambos países en años" in prompt
    assert "Algunas de las fuentes consultadas describieron el episodio" in prompt
    assert "SUPPORTED no autoriza rankings" in prompt
    assert "Los insultos de Milei desataron la crisis" in prompt
    assert "Tras los dichos de Milei, el gobierno brasileño llamó a consultas" in prompt
    assert "sin “según varias fuentes” delante de cada oración" in prompt or 'sin "según varias fuentes"' in prompt
    assert "no sustituyen un Claim para afirmaciones materialmente sensibles" in prompt
    assert "Párrafos o segmentos enteros con `claim_refs: []` son correctos" in prompt
    assert "NUNCA se convierte en hecho afirmado por Sin Línea" in prompt
    assert "Atribuir" in prompt or "según X" in prompt


def test_audit_schema_has_no_other_catchall() -> None:
    assert "OTHER" not in {item.value for item in AuditIssueType}
    assert AuditIssueType.UNATTRIBUTED_CHARACTERIZATION.value == "UNATTRIBUTED_CHARACTERIZATION"
    assert AuditIssueType.CAUSALITY.value == "CAUSALITY"


def test_unattributed_characterization_medium_is_valid_and_blocks() -> None:
    result = ArticleAuditResult(
        passed=True,
        issues=[
            AuditIssue(
                type=AuditIssueType.UNATTRIBUTED_CHARACTERIZATION,
                severity=AuditIssueSeverity.MEDIUM,
                text="la mayor crisis diplomática entre Argentina y Brasil en años",
                explanation="caracterización de fuentes escrita como hecho",
                suggested_fix=(
                    "El episodio escaló en los días siguientes con nuevas medidas diplomáticas. "
                    "Algunas de las fuentes consultadas lo describieron como uno de los conflictos "
                    "bilaterales más graves de los últimos años."
                ),
            )
        ],
    )
    normalized = normalize_audit_result(result)
    assert normalized.passed is False
    assert normalized.issues[0].type == AuditIssueType.UNATTRIBUTED_CHARACTERIZATION


def test_causality_medium_is_valid_and_blocks() -> None:
    result = ArticleAuditResult(
        passed=True,
        issues=[
            AuditIssue(
                type=AuditIssueType.CAUSALITY,
                severity=AuditIssueSeverity.MEDIUM,
                text="Los dichos de Milei desataron la crisis diplomática",
                explanation="la secuencia no respalda esa causa",
                suggested_fix=(
                    "Milei insultó a Lula durante un acto en Brasil y el gobierno brasileño "
                    "llamó a consultas a su embajador."
                ),
            )
        ],
    )
    assert normalize_audit_result(result).passed is False


def test_unattributed_characterization_low_does_not_block() -> None:
    result = ArticleAuditResult(
        passed=False,
        issues=[
            AuditIssue(
                type=AuditIssueType.UNATTRIBUTED_CHARACTERIZATION,
                severity=AuditIssueSeverity.LOW,
                text="tono menor",
                explanation="nitpick",
                suggested_fix=None,
            )
        ],
    )
    assert normalize_audit_result(result).passed is True


def test_audit_flags_evaluative_voice_and_rewrites(db_session: Session) -> None:
    event, article = _seed_draft(
        db_session,
        headline="La escandalosa decisión de la jueza kirchnerista",
    )
    article.summary = "Una polémica magistrada fulminó la ley."
    article.body = (
        "La escandalosa decisión de la jueza kirchnerista suspendió la norma. "
        "Según la jueza, «esta norma es inconstitucional»."
    )
    db_session.flush()
    blocking = ArticleAuditResult(
        passed=False,
        issues=[
            AuditIssue(
                type=AuditIssueType.ADJECTIVE,
                severity=AuditIssueSeverity.MEDIUM,
                text="escandalosa decisión de la jueza kirchnerista",
                explanation="adjetivación valorativa y etiqueta partidaria en voz de Sin Línea",
                suggested_fix="La jueza suspendió la norma.",
            )
        ],
    )
    llm = FakeStructuredLLM(
        {
            "ArticleAuditResult": [blocking, _pass_audit()],
            "ArticleDraft": [_draft(headline="Una jueza suspendió la norma")],
        }
    )
    result = _service(db_session, llm).audit(event.id, trigger="admin")
    audit_prompt = llm.user_prompts[0]
    assert "escandalosa decisión de la jueza kirchnerista" in audit_prompt
    assert "decision_by_claim_id" not in audit_prompt.casefold()
    assert result["rewrite_count"] == 1
    assert result["passed"] is True
    db_session.refresh(article)
    assert article.headline == "Una jueza suspendió la norma"


def test_audit_respects_attributed_quote_without_verification_objections(db_session: Session) -> None:
    event, article = _seed_draft(db_session)
    article.headline = "Una jueza suspendió la Ley 27.801"
    article.summary = "La magistrada cuestionó la constitucionalidad de la norma."
    article.body = (
        "La jueza María Servini suspendió la Ley 27.801. "
        "Según la jueza, «esta norma es inconstitucional porque anula garantías básicas»."
    )
    db_session.flush()
    llm = FakeStructuredLLM({"ArticleAuditResult": _pass_audit()})
    result = _service(db_session, llm).audit(event.id, trigger="admin")
    prompt = load_prompt("article_audit.md").casefold()
    user = llm.user_prompts[0]
    assert "según la jueza" in user.casefold()
    assert "no las neutralices" in prompt
    assert result["passed"] is True
    assert result["issues"] == []
    assert result["rewrite_count"] == 0
    assert "unsupported_claim" not in user.casefold()
    assert "verific" not in user.casefold() or "no verifiques" in llm.user_prompts[0].casefold()


def test_audit_approves_neutral_text_without_verification_objections(db_session: Session) -> None:
    event, article = _seed_draft(db_session)
    article.headline = "Una jueza suspendió la Ley 27.801"
    article.summary = "La resolución no está firme."
    article.body = (
        "La jueza María Servini hizo lugar a un amparo y suspendió la Ley 27.801. "
        "La decisión no está firme."
    )
    db_session.flush()
    llm = FakeStructuredLLM({"ArticleAuditResult": _pass_audit()})
    result = _service(db_session, llm).audit(event.id, trigger="admin")
    user = llm.user_prompts[0].casefold()
    assert result["passed"] is True
    assert result["issues"] == []
    assert "coverage" not in user
    assert "número" not in user
    assert "single_source" not in user
    assert "no verifiques hechos" in user


def test_unattributed_characterization_medium_triggers_rewrite_loop(db_session: Session) -> None:
    event, article = _seed_draft(db_session)
    blocking = ArticleAuditResult(
        passed=False,
        issues=[
            AuditIssue(
                type=AuditIssueType.UNATTRIBUTED_CHARACTERIZATION,
                severity=AuditIssueSeverity.MEDIUM,
                text="la mayor crisis diplomática",
                explanation="caracterización no atribuida",
                suggested_fix="Atribuí la caracterización a las fuentes",
            )
        ],
    )
    llm = FakeStructuredLLM(
        {
            "ArticleAuditResult": [blocking, _pass_audit()],
            "ArticleDraft": [_draft(headline="Corrección con atribución")],
        }
    )
    result = _service(db_session, llm).audit(event.id, trigger="admin")
    db_session.refresh(article)
    assert result["passed"] is True
    assert result["rewrite_count"] == 1
    assert result["audit_count"] == 2
    assert llm.calls == ["ArticleAuditResult", "ArticleDraft", "ArticleAuditResult"]
    assert article.headline == "Corrección con atribución"


def test_audit_schema_accepts_annotation_issue_types() -> None:
    result = ArticleAuditResult(
        passed=False,
        issues=[
            AuditIssue(
                type=AuditIssueType.INVALID_CLAIM_MAPPING,
                severity=AuditIssueSeverity.MEDIUM,
                text="fragmento",
                explanation="el claim no corresponde",
                suggested_fix="quitá la annotation",
            ),
            AuditIssue(
                type=AuditIssueType.UNMAPPED_MATERIAL_CLAIM,
                severity=AuditIssueSeverity.MEDIUM,
                text="12,22%",
                explanation="falta annotation",
                suggested_fix="asociá C1",
            ),
        ],
    )
    assert result.issues[0].type == AuditIssueType.INVALID_CLAIM_MAPPING
    assert result.issues[1].type == AuditIssueType.UNMAPPED_MATERIAL_CLAIM
    assert normalize_audit_result(result).passed is False


def test_audit_rewrite_remaps_claim_refs_to_uuid(db_session: Session) -> None:
    event, article = _seed_draft(db_session)
    claim = db_session.scalars(select(Claim).where(Claim.event_id == event.id)).one()
    rewrite = annotated_article_draft(
        "Corrección sobre Pellegrini",
        "El choque ocurrió en avenida Pellegrini.",
        paragraphs=[[("Un colectivo chocó en Pellegrini.", ["C1"])]],
    )
    llm = FakeStructuredLLM(
        {
            "ArticleAuditResult": [_fail_audit(), _pass_audit()],
            "ArticleDraft": [rewrite],
        }
    )
    result = _service(db_session, llm).audit(event.id, trigger="admin")
    db_session.refresh(article)
    assert result["passed"] is True
    assert result["rewrite_count"] == 1
    assert result["audit_count"] == 2
    assert llm.calls == ["ArticleAuditResult", "ArticleDraft", "ArticleAuditResult"]
    segment = article.body_blocks[0]["segments"][0]
    assert segment["claim_ids"] == [str(claim.id)]
    assert "claim_refs" not in segment


def _openai_rate_limit(*, message: str, code: str = "rate_limit_exceeded", retry_after: str | None = "1") -> RateLimitError:
    headers = {}
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    payload = {"error": {"message": message, "type": code, "code": code}}
    response = httpx.Response(429, request=request, headers=headers, json=payload)
    return RateLimitError(message, response=response, body=payload)


def _openai_completion(content: str):
    return SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
    )


def _openai_audit_client(outcomes: list):
    pending = list(outcomes)

    class Completions:
        def create(self, **kwargs):
            item = pending.pop(0)
            if isinstance(item, Exception):
                raise item
            return _openai_completion(item)

    return SimpleNamespace(chat=SimpleNamespace(completions=Completions()))


def test_rate_limit_after_rewrite_retries_call_without_new_version(db_session: Session, monkeypatch) -> None:
    monkeypatch.setattr("app.services.usage_recorder.record_llm_usage", lambda **_k: None)
    monkeypatch.setattr("app.providers.rate_limit.get_settings", lambda: SimpleNamespace(job_max_retries=3))
    monkeypatch.setattr("app.providers.rate_limit._jitter", lambda wait: 0.0)
    delays: list[float] = []
    monkeypatch.setattr("app.providers.rate_limit.time.sleep", delays.append)
    event, article = _seed_draft(db_session)
    version_before = article.current_version
    client = _openai_audit_client(
        [
            _fail_audit().model_dump_json(),
            _draft(headline="Draft corregido").model_dump_json(),
            _openai_rate_limit(message="Rate limit reached for gpt-4o. Please try again in 19.908s.", retry_after="20"),
            _pass_audit().model_dump_json(),
        ]
    )
    llm = OpenAIStructuredProvider(api_key="k", model="gpt-4o", client=client)
    result = AuditService(db_session, llm=llm, writer=llm).audit(event.id, trigger="admin")
    db_session.refresh(article)
    assert result["passed"] is True
    assert result["rewrite_count"] == 1
    assert article.current_version == version_before + 1
    assert article.headline == "Draft corregido"
    assert delays == [20.0]
    published = PublishService(db_session).publish(event.id, trigger="test")
    assert published["published"] is True


def test_rate_limit_exhausted_after_rewrite_does_not_duplicate_or_publish(db_session: Session, monkeypatch) -> None:
    monkeypatch.setattr("app.services.usage_recorder.record_llm_usage", lambda **_k: None)
    monkeypatch.setattr("app.providers.rate_limit.get_settings", lambda: SimpleNamespace(job_max_retries=1))
    monkeypatch.setattr("app.providers.rate_limit._jitter", lambda wait: 0.0)
    monkeypatch.setattr("app.providers.rate_limit.time.sleep", lambda _s: None)
    event, article = _seed_draft(db_session)
    client = _openai_audit_client(
        [
            _fail_audit().model_dump_json(),
            _draft(headline="Draft corregido").model_dump_json(),
            _openai_rate_limit(message="Rate limit reached for gpt-4o. Please try again in 19.908s.", retry_after="20"),
            _openai_rate_limit(message="Rate limit reached for gpt-4o. Please try again in 19.908s.", retry_after="20"),
        ]
    )
    llm = OpenAIStructuredProvider(api_key="k", model="gpt-4o", client=client)
    result = AuditService(db_session, llm=llm, writer=llm).audit(event.id, trigger="admin")
    db_session.refresh(article)
    runs = list(
        db_session.scalars(
            select(PipelineRun)
            .where(PipelineRun.event_id == event.id, PipelineRun.stage == AUDITING_STAGE)
            .order_by(PipelineRun.started_at)
        )
    )
    assert result["audited"] is False
    assert result.get("passed") is not True
    assert result.get("reason") == "rate_limit_exceeded"
    assert article.current_version == 2
    assert article.headline == "Draft corregido"
    assert runs[-1].status == PipelineStatus.FAILED
    assert runs[-1].error_message
    assert PublishService(db_session).publish(event.id, trigger="test")["reason"] == "audit_not_passed"


def test_insufficient_quota_does_not_retry_or_count_as_editorial(db_session: Session, monkeypatch) -> None:
    monkeypatch.setattr("app.services.usage_recorder.record_llm_usage", lambda **_k: None)
    delays: list[float] = []
    monkeypatch.setattr("app.providers.rate_limit.time.sleep", delays.append)
    event, article = _seed_draft(db_session)
    version = article.current_version
    client = _openai_audit_client(
        [
            _openai_rate_limit(
                message="You exceeded your current quota",
                code="insufficient_quota",
                retry_after="1",
            )
        ]
    )
    llm = OpenAIStructuredProvider(api_key="k", model="gpt-4o", client=client)
    result = AuditService(db_session, llm=llm, writer=llm).audit(event.id, trigger="admin")
    db_session.refresh(article)
    assert delays == []
    assert result["audited"] is False
    assert result.get("reason") == "insufficient_quota"
    assert article.current_version == version
    assert PublishService(db_session).publish(event.id, trigger="test")["reason"] == "audit_not_passed"
