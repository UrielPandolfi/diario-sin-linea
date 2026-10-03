from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.clock import utc_now
from app.domain.enums import ClaimImportance, ClaimStatus, EventSourceRelation, PipelineStatus
from app.main import app
from app.models import ArticleVersion, Claim, EventSource, PipelineRun
from app.schemas import ArticleContentUpdate
from app.schemas.auditing import AuditIssue, AuditIssueAction, AuditIssueReason, AuditIssueSeverity, AuditIssueType
from app.services.article_service import ArticleService
from app.services.rejected_drafts import (
    GENERAL_REASON,
    TECHNICAL_REASON,
    governing_audit,
    has_full_draft_text,
    reader_reasons,
    rejection_mode,
)
from tests.editorial_snapshot import persist_version_snapshot
from tests.reader_session import authenticate_reader
from tests.test_public_api import _item, _publish_passed, _seed, _source


def _moment(minutes: int) -> datetime:
    return datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc) + timedelta(minutes=minutes)


def _issue(
    reason: AuditIssueReason,
    *,
    severity: AuditIssueSeverity = AuditIssueSeverity.HIGH,
    text: str = "El intendente confirmó el número",
    explanation: str = "CANARIO_INTERNO_SNAPSHOT",
    issue_type: AuditIssueType = AuditIssueType.UNSUPPORTED_CLAIM,
) -> AuditIssue:
    return AuditIssue(
        type=issue_type,
        severity=severity,
        text=text,
        explanation=explanation,
        suggested_fix="NO_MOSTRAR_FIX",
        reason=reason,
        action=AuditIssueAction.REVIEW,
    )


def _surface() -> SimpleNamespace:
    return SimpleNamespace(
        headline="Titular del borrador",
        summary="Bajada del borrador",
        body="Cuerpo del borrador.",
        body_blocks=None,
    )


def _run(
    *,
    stage: str = "auditing",
    status: PipelineStatus = PipelineStatus.SUCCESS,
    minutes: int,
    meta: dict,
) -> SimpleNamespace:
    moment = _moment(minutes)
    return SimpleNamespace(
        stage=stage,
        status=status,
        started_at=moment,
        finished_at=moment,
        metadata_json=meta,
        error_message=None,
    )


def _bind_audit(
    session: Session,
    event,
    article,
    *,
    passed: bool,
    issues: list[AuditIssue] | None = None,
    technical: bool = False,
    minutes: int = 5,
    at: datetime | None = None,
    version: int | None = None,
    error: str | None = None,
    status: PipelineStatus | None = None,
) -> PipelineRun:
    number = int(article.current_version if version is None else version)
    writing = session.scalars(
        select(PipelineRun)
        .where(PipelineRun.event_id == event.id, PipelineRun.stage == "writing")
        .order_by(PipelineRun.started_at.desc())
    ).first()
    snap = {}
    if writing is not None:
        stored = (writing.metadata_json or {}).get("evidence_snapshot")
        if isinstance(stored, dict):
            snap = dict(stored)
    snap["version"] = number
    moment = at or _moment(minutes)
    if technical:
        meta = {
            "audited": False,
            "passed": None,
            "technical_ok": False,
            "reason": "insufficient_quota",
            "version_after": number,
            "evidence_snapshot": snap,
            "issues": [],
        }
        run_status = PipelineStatus.FAILED
    elif passed:
        meta = {
            "audited": True,
            "passed": True,
            "technical_ok": True,
            "reason": "passed",
            "version_after": number,
            "evidence_snapshot": snap,
            "issues": [],
        }
        run_status = PipelineStatus.SUCCESS
    else:
        meta = {
            "audited": True,
            "passed": False,
            "technical_ok": True,
            "reason": "structural_block",
            "version_after": number,
            "evidence_snapshot": snap,
            "issues": [issue.model_dump(mode="json") for issue in issues or []],
        }
        run_status = status or PipelineStatus.SUCCESS
    run = PipelineRun(
        event_id=event.id,
        stage="auditing",
        status=run_status,
        started_at=moment,
        finished_at=moment,
        error_message=error,
        metadata_json=meta,
    )
    session.add(run)
    session.flush()
    return run


def test_reader_reasons_keep_blocking_causes_of_this_version() -> None:
    high = _issue(AuditIssueReason.UNBACKED_MATERIAL, text="el puente quedó cortado")
    low = _issue(
        AuditIssueReason.SEMANTIC_SHIFT,
        severity=AuditIssueSeverity.LOW,
        text="frase menor de advertencia",
        explanation="HALLAZGO_BAJO_NO_MOSTRAR",
    )
    reasons = reader_reasons(
        [high.model_dump(mode="json"), low.model_dump(mode="json"), {"type": "NOPE"}],
        article=_surface(),
        snapshot={"article_context": {}},
        mode="editorial",
    )
    blob = " ".join(item["text"] for item in reasons)
    assert reasons[0]["category"] == "missing_support"
    assert "respaldo" in blob
    assert "el puente quedó cortado" in blob
    assert "HALLAZGO_BAJO_NO_MOSTRAR" not in blob
    assert "frase menor" not in blob
    assert "CANARIO_INTERNO_SNAPSHOT" not in blob
    assert "NO_MOSTRAR_FIX" not in blob


def test_reader_reasons_do_not_invent_a_cause() -> None:
    reasons = reader_reasons(
        [{"type": "NOPE", "severity": "HIGH", "text": "x", "explanation": "interno"}],
        article=_surface(),
        snapshot=None,
        mode="editorial",
    )
    assert reasons == [GENERAL_REASON]
    technical = reader_reasons(
        [_issue(AuditIssueReason.UNBACKED_MATERIAL).model_dump(mode="json")],
        article=_surface(),
        snapshot=None,
        mode="technical",
    )
    assert technical == [TECHNICAL_REASON]
    assert "falso" not in technical[0]["text"]
    assert "respaldo" not in technical[0]["text"]


def test_later_pass_of_the_same_version_drops_the_earlier_rejection() -> None:
    failed = _run(
        minutes=1,
        meta={"audited": True, "passed": False, "version_after": 1, "issues": [{"reason": "unbacked_material"}]},
    )
    passed = _run(
        minutes=2,
        meta={"audited": True, "passed": True, "version_after": 1, "issues": []},
    )
    governing = governing_audit([passed, failed], 1)
    assert rejection_mode(governing) is None
    assert has_full_draft_text(SimpleNamespace(headline=" ", summary="Bajada", body="Cuerpo")) is False


def test_anonymous_reader_gets_no_rejected_draft(db_session: Session) -> None:
    _event, article = _seed(db_session, locality="Rosario", headline="Borrador secreto Pellegrini", hash_key="rejanon")
    _bind_audit(
        db_session,
        _event,
        article,
        passed=False,
        issues=[_issue(AuditIssueReason.SURFACE_ATTRIBUTION, text="según nadie quedó confirmado")],
    )
    db_session.commit()
    with TestClient(app) as anon:
        listing = anon.get("/api/v1/transparency/rejected-drafts")
        detail = anon.get(f"/api/v1/transparency/rejected-drafts/{article.id}")
        public = anon.get(f"/api/v1/articles/{article.slug}")
        sitemap = anon.get("/api/v1/sitemap-articles")
    assert listing.status_code == 401
    assert listing.headers["cache-control"] == "private, no-store"
    assert listing.headers["x-robots-tag"] == "noindex, nofollow"
    assert detail.status_code == 401
    assert detail.headers["cache-control"] == "private, no-store"
    assert "Borrador secreto Pellegrini" not in listing.text
    assert "Borrador secreto Pellegrini" not in detail.text
    assert "CANARIO_INTERNO_SNAPSHOT" not in listing.text
    assert public.status_code == 404
    assert article.slug not in sitemap.text


def test_reader_sees_the_blocking_reason_of_the_current_version(db_session: Session) -> None:
    event, article = _seed(db_session, locality="Rosario", headline="Borrador con atribución rota", hash_key="rejread")
    _bind_audit(
        db_session,
        event,
        article,
        passed=False,
        minutes=1,
        issues=[_issue(AuditIssueReason.UNBACKED_MATERIAL, text="MOTIVO_VIEJO_UNICO")],
    )
    _bind_audit(
        db_session,
        event,
        article,
        passed=False,
        minutes=3,
        issues=[
            _issue(AuditIssueReason.SURFACE_ATTRIBUTION, text="falta decir quién lo afirmó"),
            _issue(
                AuditIssueReason.SEMANTIC_SHIFT,
                severity=AuditIssueSeverity.LOW,
                text="una coma de más",
                explanation="HALLAZGO_BAJO_NO_MOSTRAR",
                issue_type=AuditIssueType.CLARITY,
            ),
        ],
    )
    before_runs = db_session.scalar(select(func.count()).select_from(PipelineRun))
    db_session.commit()
    with TestClient(app) as client:
        authenticate_reader(client, email="borradores@sinlinea.test")
        listing = client.get("/api/v1/transparency/rejected-drafts")
        detail = client.get(f"/api/v1/transparency/rejected-drafts/{article.id}")
        admin = client.get("/api/v1/admin/me")
    db_session.expire_all()
    after_runs = db_session.scalar(select(func.count()).select_from(PipelineRun))
    assert listing.status_code == 200
    assert listing.headers["cache-control"] == "private, no-store"
    assert listing.headers["x-robots-tag"] == "noindex, nofollow"
    items = listing.json()["items"]
    assert len(items) == 1
    assert items[0]["headline"] == "Borrador con atribución rota"
    assert items[0]["label"] == "Borrador no aprobado"
    assert "atribuir" in items[0]["reason"]
    assert "MOTIVO_VIEJO_UNICO" not in listing.text
    assert "body" not in items[0]
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["summary"].startswith("Resumen")
    assert "colectivo" in payload["body"].lower() or payload["body"]
    assert payload["body"] == article.body or "chocó" in payload["body"] or "Borrador" in payload["body"]
    assert any(reason["category"] == "attribution" for reason in payload["reasons"])
    assert "HALLAZGO_BAJO_NO_MOSTRAR" not in detail.text
    assert "CANARIO_INTERNO_SNAPSHOT" not in detail.text
    assert "NO_MOSTRAR_FIX" not in detail.text
    assert "evidence_snapshot" not in payload
    assert "issues" not in payload
    assert "suggested_fix" not in payload
    assert admin.status_code == 401
    assert before_runs == after_runs


def test_statuses_without_a_concluded_rejection_stay_out(db_session: Session) -> None:
    bare_event, bare = _seed(db_session, locality="Rosario", headline="Solo un draft sin auditoria", hash_key="rejbare")
    approved_event, approved = _seed(db_session, locality="Rosario", headline="Candidata ya aprobada", hash_key="rejok")
    _bind_audit(db_session, approved_event, approved, passed=True, minutes=2)
    empty_event, empty = _seed(db_session, locality="Rosario", headline="Texto vacio no cuenta", hash_key="rejempty")
    empty_version = db_session.scalars(select(ArticleVersion).where(ArticleVersion.article_id == empty.id)).one()
    empty_version.body = " "
    empty.body = " "
    _bind_audit(
        db_session,
        empty_event,
        empty,
        passed=False,
        issues=[_issue(AuditIssueReason.UNBACKED_MATERIAL, text="motivo de un texto vacio")],
    )
    busy_event, busy = _seed(db_session, locality="Rosario", headline="Sigue en auditoria", hash_key="rejbusy")
    _bind_audit(
        db_session,
        busy_event,
        busy,
        passed=False,
        minutes=1,
        issues=[_issue(AuditIssueReason.UNBACKED_MATERIAL, text="motivo que no debe listarse")],
    )
    db_session.add(
        PipelineRun(
            event_id=busy_event.id,
            stage="auditing",
            status=PipelineStatus.RUNNING,
            started_at=_moment(9),
            metadata_json={"version_after": busy.current_version},
        )
    )
    db_session.commit()
    del bare
    with TestClient(app) as client:
        authenticate_reader(client, email="filtros@sinlinea.test")
        listing = client.get("/api/v1/transparency/rejected-drafts")
    headlines = {item["headline"] for item in listing.json()["items"]}
    assert "Solo un draft sin auditoria" not in headlines
    assert "Candidata ya aprobada" not in headlines
    assert "Texto vacio no cuenta" not in headlines
    assert "Sigue en auditoria" not in headlines


def test_rejected_update_does_not_replace_the_published_article(db_session: Session) -> None:
    event, article = _seed(db_session, locality="Rosario", headline="Puente publicado intacto", hash_key="rejupd")
    published_body = article.body
    _publish_passed(db_session, event)
    db_session.refresh(article)
    assert article.published_version == 1
    ArticleService(db_session).update_content(
        article,
        ArticleContentUpdate(
            headline="Actualización no aprobada del puente",
            summary="Bajada que no debe reemplazar la nota",
            body="Cuerpo xilofonorechazado que no forma parte de la nota publicada.",
            change_reason="material_change",
        ),
    )
    db_session.flush()
    persist_version_snapshot(db_session, event, article)
    claim = db_session.scalars(select(Claim).where(Claim.event_id == event.id)).one()
    version = db_session.scalars(
        select(ArticleVersion).where(
            ArticleVersion.article_id == article.id,
            ArticleVersion.version_number == article.current_version,
        )
    ).one()
    blocks = [{"type": "paragraph", "segments": [{"text": version.body, "claim_ids": [str(claim.id)]}]}]
    version.body_blocks = blocks
    article.body_blocks = blocks
    _bind_audit(
        db_session,
        event,
        article,
        passed=False,
        at=utc_now() + timedelta(hours=2),
        issues=[_issue(AuditIssueReason.SURFACE_CATEGORICAL, text="el hecho quedó demostrado")],
    )
    claim.status = ClaimStatus.DISPROVEN
    db_session.add(
        Claim(
            event_id=event.id,
            canonical_text="HECHO_POSTERIOR_NO_MOSTRAR",
            claim_type="hecho",
            importance=ClaimImportance.HIGH,
            status=ClaimStatus.DISPROVEN,
        )
    )
    later = _source(
        db_session,
        name="Diario Posterior Ajeno",
        domain="posterior.test",
        feed_url="https://posterior.test/rss.xml",
    )
    later_item = _item(
        db_session,
        later.id,
        url="https://posterior.test/nota",
        title="Nota posterior",
        body="Texto posterior que no pertenece a la version rechazada.",
        content_hash="rejupd-later",
    )
    db_session.add(
        EventSource(
            event_id=event.id,
            source_item_id=later_item.id,
            relation_type=EventSourceRelation.ADDITIONAL,
        )
    )
    audit = db_session.scalars(
        select(PipelineRun)
        .where(
            PipelineRun.event_id == event.id,
            PipelineRun.stage == "auditing",
            PipelineRun.status == PipelineStatus.SUCCESS,
        )
        .order_by(PipelineRun.started_at.desc())
    ).first()
    assert audit is not None
    assert (audit.metadata_json or {}).get("passed") is False
    meta = dict(audit.metadata_json or {})
    snap = dict(meta.get("evidence_snapshot") or {})
    context = dict(snap.get("article_context") or {})
    context["sources"] = [
        {
            "ref": 1,
            "name": "Fuente De Esta Version",
            "domain": "esta-version.test",
            "url": "https://esta-version.test/nota",
            "title": "Titulo legible de la nota",
            "relation_type": "INITIAL",
        }
    ]
    snap["article_context"] = context
    snap["version"] = article.current_version
    meta["evidence_snapshot"] = snap
    meta["version_after"] = article.current_version
    audit.metadata_json = meta
    db_session.commit()
    published_version = article.published_version
    with TestClient(app) as anon, TestClient(app) as reader:
        public = anon.get(f"/api/v1/articles/{article.slug}")
        search = anon.get("/api/v1/search", params={"q": "xilofonorechazado"})
        authenticate_reader(reader, email="actualizacion@sinlinea.test")
        search_reader = reader.get("/api/v1/search", params={"q": "xilofonorechazado"})
        feed = reader.get("/api/v1/feed")
        now = reader.get("/api/v1/now")
        detail = reader.get(f"/api/v1/transparency/rejected-drafts/{article.id}")
    assert public.status_code == 200
    assert public.json()["headline"] == "Puente publicado intacto"
    assert public.json()["body"] == published_body
    assert "xilofonorechazado" not in public.text
    assert "Actualización no aprobada" not in public.text
    assert search.status_code == 401
    assert "xilofonorechazado" not in search.text
    assert search_reader.status_code == 200
    assert search_reader.json()["items"] == []
    assert "Actualización no aprobada del puente" not in search_reader.text
    assert "Actualización no aprobada del puente" not in feed.text
    assert "xilofonorechazado" not in now.text
    assert detail.status_code == 200
    body = detail.json()
    assert body["label"] == "Actualización no aprobada"
    assert body["headline"] == "Actualización no aprobada del puente"
    assert "xilofonorechazado" in body["body"]
    assert body["published_path"] == f"/noticias/{article.slug}"
    assert any(reason["category"] == "overcertainty" for reason in body["reasons"])
    assert "HECHO_POSTERIOR_NO_MOSTRAR" not in detail.text
    assert "Diario Posterior Ajeno" not in detail.text
    assert "Fuente De Esta Version" in detail.text
    assert body["claims"]
    assert all(claim_row["status"] != "DISPROVEN" for claim_row in body["claims"])
    db_session.expire_all()
    db_session.refresh(article)
    assert article.published_version == published_version
    assert article.published_version != article.current_version


def test_technical_failure_is_not_presented_as_falsehood(db_session: Session) -> None:
    event, article = _seed(db_session, locality="Rosario", headline="Borrador con fallo tecnico", hash_key="rejtech")
    _bind_audit(
        db_session,
        event,
        article,
        passed=False,
        technical=True,
        error="insufficient_quota sk-live-secret-token",
    )
    db_session.commit()
    with TestClient(app) as client:
        authenticate_reader(client, email="tecnico@sinlinea.test")
        detail = client.get(f"/api/v1/transparency/rejected-drafts/{article.id}")
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["reasons"] == [TECHNICAL_REASON]
    assert "sk-live-secret-token" not in detail.text
    assert "insufficient_quota" not in detail.text
    assert "falso" not in detail.text


def test_rejected_drafts_are_paginated_without_duplicates(db_session: Session) -> None:
    first_event, first = _seed(db_session, locality="Rosario", headline="Primer borrador rechazado", hash_key="rejpage1")
    second_event, second = _seed(db_session, locality="Rosario", headline="Segundo borrador rechazado", hash_key="rejpage2")
    _bind_audit(
        db_session,
        first_event,
        first,
        passed=False,
        minutes=2,
        issues=[_issue(AuditIssueReason.CENTRAL_UNVERIFIED)],
    )
    _bind_audit(
        db_session,
        second_event,
        second,
        passed=False,
        minutes=4,
        issues=[_issue(AuditIssueReason.CENTRAL_UNVERIFIED)],
    )
    db_session.commit()
    with TestClient(app) as client:
        authenticate_reader(client, email="pagina@sinlinea.test")
        page = client.get("/api/v1/transparency/rejected-drafts", params={"limit": 1})
        assert page.status_code == 200
        body = page.json()
        assert len(body["items"]) == 1
        assert body["items"][0]["headline"] == "Segundo borrador rechazado"
        assert body["next_cursor"]
        nxt = client.get("/api/v1/transparency/rejected-drafts", params={"limit": 1, "cursor": body["next_cursor"]})
        bad = client.get("/api/v1/transparency/rejected-drafts", params={"cursor": "no-es-un-cursor"})
    assert nxt.status_code == 200
    assert [item["headline"] for item in nxt.json()["items"]] == ["Primer borrador rechazado"]
    assert nxt.json()["next_cursor"] is None
    assert bad.status_code == 400
    assert "Primer borrador" not in bad.text
    assert "Segundo borrador" not in bad.text
