from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import (
    ClaimImportance,
    ClaimStatus,
    EvidenceType,
    IngestionMethod,
    PipelineStatus,
)
from app.models import Article, Claim, ClaimEvidence, PipelineRun
from app.providers.fakes import FakeStructuredLLM
from app.schemas import ArticleCreate, EventCreate, SourceCreate, SourceItemCreate
from app.schemas.auditing import ArticleAuditResult, AuditIssue, AuditIssueReason, AuditIssueSeverity, AuditIssueType
from app.services.article_service import ArticleService
from app.services.audit_policy import (
    merge_audit_result,
    signals_plural_corroboration,
    signals_unattributed_effective_date,
    structural_findings,
)
from app.services.audit_service import AuditService
from app.services.event_service import EventService
from app.services.evidence_snapshot import evidence_snapshot_for_version
from app.services.publish_service import PublishService
from app.services.source_item_service import SourceItemService
from app.services.source_service import SourceService
from app.services.writing_service import WritingService
from app.core.article_body import plain_article_draft
from tests.editorial_snapshot import persist_version_snapshot


def _source(session: Session):
    return SourceService(session).create(
        SourceCreate(
            name="LN+",
            preferred_ingestion_method=IngestionMethod.RSS,
            feed_url="https://www.lnmas.test/rss.xml",
            is_monitored=True,
            is_enabled=True,
            domain="lnmas.test",
        )
    )


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
        "title_internal": "Presentaron una denuncia penal contra Alberto Fernández",
        "event_type": "denuncia",
        "source_item_id": item.id,
        "started_at": datetime.now(timezone.utc),
        "locality": "Buenos Aires",
        "province": "Buenos Aires",
        "short_summary": "Denuncia",
    }
    payload.update(overrides)
    return EventService(session).create(EventCreate(**payload))


def _claim(session: Session, event, *, text: str, status: ClaimStatus = ClaimStatus.SINGLE_SOURCE):
    row = Claim(
        event_id=event.id,
        canonical_text=text,
        claim_type="hecho",
        importance=ClaimImportance.HIGH,
        status=status,
    )
    session.add(row)
    session.flush()
    return row


def _draft_article(session: Session, event, *, headline: str, summary: str, body: str):
    article, _created = ArticleService(session).create_draft(
        ArticleCreate(event_id=event.id, headline=headline, summary=summary, body=body)
    )
    session.flush()
    return article


def _optimistic():
    return FakeStructuredLLM({"ArticleAuditResult": ArticleAuditResult(passed=True, issues=[])})


def test_optimistic_auditor_cannot_silence_structural(db_session: Session) -> None:
    structural = structural_findings(None, type("A", (), {"headline": "x", "body_blocks": None})())
    llm = ArticleAuditResult(passed=True, issues=[])
    merged = merge_audit_result(llm, structural=structural)
    assert merged.passed is False
    assert merged.editorial_passed is False
    assert any(issue.reason == AuditIssueReason.CONTRACT_MISSING for issue in merged.issues)


def test_alberto_coverage_gap_blocks_optimistic_and_attribution(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(
        db_session,
        source.id,
        url="https://lnmas.test/alberto",
        title="Denuncia",
        body="Críticas a los F-16. Según LN+ habrá sorteo de juez.",
        content_hash="alb",
    )
    event = _event(db_session, item)
    _claim(db_session, event, text="Alberto Fernández mencionó a los F-16")
    article = _draft_article(
        db_session,
        event,
        headline="Presentaron una denuncia penal contra Alberto Fernández por traición a la patria",
        summary="Según la denuncia, el ex presidente cometió el delito.",
        body="Según LN+, el sorteo de juez será la semana próxima. Advertencia genérica al pie.",
    )
    persist_version_snapshot(db_session, event, article, coverage_gap=True)
    result = AuditService(db_session, llm=_optimistic()).audit(event.id, trigger="test")
    published = PublishService(db_session).publish(event.id, trigger="test")
    assert result["passed"] is False
    assert result["reason"] == "structural_block"
    assert any(issue.get("reason") == AuditIssueReason.CENTRAL_UNCOVERED.value for issue in result["issues"])
    assert published["reason"] == "audit_not_passed"


def test_paraphrased_title_does_not_close_coverage_gap(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(db_session, source.id, url="https://lnmas.test/alb2", title="D", body="F-16", content_hash="alb2")
    event = _event(db_session, item)
    _claim(db_session, event, text="Críticas a los F-16")
    article = _draft_article(
        db_session,
        event,
        headline="Según una presentación, hay una causa abierta",
        summary="Según la denuncia, el hecho ocurrió.",
        body="El texto no copia el título original.",
    )
    persist_version_snapshot(db_session, event, article, coverage_gap=True)
    result = AuditService(db_session, llm=_optimistic()).audit(event.id, trigger="test")
    assert result["passed"] is False
    assert any(issue.get("reason") == AuditIssueReason.CENTRAL_UNCOVERED.value for issue in result["issues"])


def test_central_unverified_blocks_even_if_title_omits_it(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(db_session, source.id, url="https://ejemplo.test/c", title="Choque", body="Choque", content_hash="c1")
    event = _event(db_session, item, title_internal="Choque en Pellegrini")
    claim = _claim(db_session, event, text="Un colectivo chocó en Pellegrini", status=ClaimStatus.SUPPORTED)
    article = _draft_article(
        db_session,
        event,
        headline="Choque en Pellegrini",
        summary="Hubo un choque.",
        body="Un colectivo chocó en Pellegrini.",
    )
    persist_version_snapshot(db_session, event, article, central_unverified=[str(claim.id)])
    result = AuditService(db_session, llm=_optimistic()).audit(event.id, trigger="test")
    assert result["passed"] is False
    assert any(issue.get("reason") == AuditIssueReason.CENTRAL_UNVERIFIED.value for issue in result["issues"])
    assert PublishService(db_session).publish(event.id, trigger="test")["reason"] == "audit_not_passed"


def test_unpaired_pair_blocks_optimistic(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(db_session, source.id, url="https://ejemplo.test/p", title="Choque", body="Choque", content_hash="p1")
    event = _event(db_session, item, title_internal="Choque en Pellegrini")
    _claim(db_session, event, text="Un colectivo chocó", status=ClaimStatus.SUPPORTED)
    article = _draft_article(db_session, event, headline="Choque", summary="Choque", body="Un colectivo chocó.")
    persist_version_snapshot(db_session, event, article, stale=True)
    result = AuditService(db_session, llm=_optimistic()).audit(event.id, trigger="test")
    assert result["passed"] is False
    assert any(issue.get("reason") == AuditIssueReason.CONTRACT_UNPAIRED.value for issue in result["issues"])


def test_secondary_deferred_does_not_block(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(db_session, source.id, url="https://ejemplo.test/s", title="Choque", body="Choque", content_hash="d1")
    event = _event(db_session, item, title_internal="Choque en Pellegrini")
    _claim(db_session, event, text="Un colectivo chocó en Pellegrini", status=ClaimStatus.SUPPORTED)
    article = _draft_article(
        db_session, event, headline="Choque en Pellegrini", summary="Hubo un choque.", body="Un colectivo chocó."
    )
    persist_version_snapshot(
        db_session,
        event,
        article,
        deferred=[{"claim_id": "secondary-unused", "reason": "budget"}],
    )
    result = AuditService(db_session, llm=_optimistic()).audit(event.id, trigger="test")
    assert result["passed"] is True
    published = PublishService(db_session).publish(event.id, trigger="test")
    assert published["published"] is True


def test_single_source_evaluated_is_not_unverified(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(db_session, source.id, url="https://ejemplo.test/ss", title="Dijo", body="Dijo", content_hash="u1")
    event = _event(db_session, item, title_internal="Bregman habló")
    _claim(db_session, event, text="Bregman dijo que es un vejestorio jurídico", status=ClaimStatus.SINGLE_SOURCE)
    article = _draft_article(
        db_session,
        event,
        headline="Bregman criticó el régimen",
        summary="Según la versión taquigráfica, Bregman dijo que es un vejestorio jurídico.",
        body="Según la versión taquigráfica, Bregman dijo que es un vejestorio jurídico.",
    )
    persist_version_snapshot(db_session, event, article)
    result = AuditService(db_session, llm=_optimistic()).audit(event.id, trigger="test")
    assert result["passed"] is True
    assert not any(issue.get("reason") == AuditIssueReason.CENTRAL_UNVERIFIED.value for issue in result["issues"])


def test_snapshot_ignores_claims_added_after_write(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(db_session, source.id, url="https://ejemplo.test/w", title="Choque", body="Choque", content_hash="w1")
    event = _event(db_session, item, title_internal="Choque en Pellegrini")
    _claim(db_session, event, text="Un colectivo chocó en Pellegrini", status=ClaimStatus.SUPPORTED)
    from tests.editorial_snapshot import attach_verify_to_latest_claim_run
    from app.services.claim_coverage import claims_fingerprint
    from app.services.claim_service import CLAIM_STAGE

    fp = claims_fingerprint(list(event.claims))
    claim_run = PipelineRun(
        event_id=event.id,
        stage=CLAIM_STAGE,
        status=PipelineStatus.SUCCESS,
        finished_at=datetime.now(timezone.utc),
        metadata_json={"claims_fingerprint": fp, "coverage": {"coverage_gap": False, "expected_central": []}},
    )
    db_session.add(claim_run)
    db_session.flush()
    attach_verify_to_latest_claim_run(db_session, event)
    written = WritingService(
        db_session, llm=FakeStructuredLLM({"ArticleDraft": plain_article_draft("Choque", "Resumen", "Un colectivo chocó.")})
    ).write(event.id, trigger="test")
    assert written["written"] is True
    frozen = written["claims_fingerprint"]
    extra = _claim(db_session, event, text="Hubo un sorteo de juez mañana", status=ClaimStatus.SUPPORTED)
    db_session.flush()
    article = db_session.scalars(select(Article).where(Article.event_id == event.id)).one()
    runs = list(db_session.scalars(select(PipelineRun).where(PipelineRun.event_id == event.id)))
    snap = evidence_snapshot_for_version(sorted(runs, key=lambda row: row.started_at, reverse=True), article.current_version)
    assert snap is not None
    assert snap["claims_fingerprint"] == frozen
    assert str(extra.id) not in (snap.get("article_context") or {}).get("claim_refs", {}).values()
    result = AuditService(db_session, llm=_optimistic()).audit(event.id, trigger="test")
    assert result["passed"] is True
    assert result["claims_fingerprint"] == frozen


def test_version_change_between_audit_and_publish_blocks(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(db_session, source.id, url="https://ejemplo.test/v", title="Choque", body="Choque", content_hash="v1")
    event = _event(db_session, item, title_internal="Choque en Pellegrini")
    _claim(db_session, event, text="Un colectivo chocó", status=ClaimStatus.SUPPORTED)
    article = _draft_article(db_session, event, headline="Choque", summary="Choque", body="Un colectivo chocó.")
    persist_version_snapshot(db_session, event, article)
    audited = AuditService(db_session, llm=_optimistic()).audit(event.id, trigger="test")
    assert audited["passed"] is True
    from app.schemas import ArticleContentUpdate

    ArticleService(db_session).update_content(
        article,
        ArticleContentUpdate(headline="Otro texto", summary="Nuevo", body="Cuerpo no auditado.", change_reason="edit"),
    )
    blocked = PublishService(db_session).publish(event.id, trigger="test")
    assert blocked["published"] is False
    assert blocked["reason"] == "audit_not_passed"


def test_failed_audit_after_pass_does_not_approve(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(db_session, source.id, url="https://ejemplo.test/f", title="Choque", body="Choque", content_hash="f1")
    event = _event(db_session, item, title_internal="Choque en Pellegrini")
    _claim(db_session, event, text="Un colectivo chocó", status=ClaimStatus.SUPPORTED)
    article = _draft_article(db_session, event, headline="Choque", summary="Choque", body="Un colectivo chocó.")
    persist_version_snapshot(db_session, event, article)
    assert AuditService(db_session, llm=_optimistic()).audit(event.id, trigger="test")["passed"] is True
    boom = FakeStructuredLLM({"ArticleAuditResult": RuntimeError("timeout")})
    failed = AuditService(db_session, llm=boom).audit(event.id, trigger="test")
    assert failed.get("error")
    blocked = PublishService(db_session).publish(event.id, trigger="test")
    assert blocked["reason"] == "audit_not_passed"


def test_rewrite_failed_does_not_reuse_prior_pass(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(db_session, source.id, url="https://ejemplo.test/r", title="Choque", body="Choque", content_hash="rw1")
    event = _event(db_session, item, title_internal="Choque en Pellegrini")
    _claim(db_session, event, text="Un colectivo chocó", status=ClaimStatus.SUPPORTED)
    article = _draft_article(db_session, event, headline="Choque", summary="Choque", body="Un colectivo chocó.")
    persist_version_snapshot(db_session, event, article)
    first = AuditService(db_session, llm=_optimistic()).audit(event.id, trigger="test")
    assert first["passed"] is True
    version_passed = article.current_version
    blocking = ArticleAuditResult(
        passed=False,
        issues=[
            AuditIssue(
                type=AuditIssueType.UNSUPPORTED_CLAIM,
                severity=AuditIssueSeverity.HIGH,
                text="dato",
                explanation="falta",
                suggested_fix="quitá",
            )
        ],
    )
    cap = FakeStructuredLLM(
        {
            "ArticleAuditResult": [blocking, blocking, blocking],
            "ArticleDraft": [
                plain_article_draft("Uno", "s", "c"),
                plain_article_draft("Dos", "s", "c"),
            ],
        }
    )
    exhausted = AuditService(db_session, llm=cap, writer=cap).audit(event.id, trigger="test")
    db_session.refresh(article)
    assert exhausted["passed"] is False
    assert article.current_version > version_passed
    assert PublishService(db_session).publish(event.id, trigger="test")["reason"] == "audit_not_passed"


def test_plural_and_negation_helpers() -> None:
    assert signals_plural_corroboration("Quedó confirmado por varias fuentes independientes.") is True
    assert signals_plural_corroboration("No hay varias fuentes independientes que lo acrediten.") is False
    assert signals_unattributed_effective_date("El nuevo régimen penal juvenil comenzó a regir.") is True
    assert signals_unattributed_effective_date("Según Bregman, la norma comenzó a regir.") is False
    assert signals_unattributed_effective_date("No está confirmado que comenzó a regir.") is False


def test_invented_attribution_blocked_when_llm_reports(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(db_session, source.id, url="https://lnmas.test/inv", title="Choque", body="Choque", content_hash="i1")
    event = _event(db_session, item, title_internal="Choque en Pellegrini")
    _claim(db_session, event, text="Un colectivo chocó", status=ClaimStatus.SUPPORTED)
    article = _draft_article(
        db_session,
        event,
        headline="Choque",
        summary="Según LN+, el juez será sorteado mañana.",
        body="Según LN+, el juez será sorteado mañana.",
    )
    persist_version_snapshot(db_session, event, article)
    llm = FakeStructuredLLM(
        {
            "ArticleAuditResult": ArticleAuditResult(
                passed=False,
                issues=[
                    AuditIssue(
                        type=AuditIssueType.UNSUPPORTED_CLAIM,
                        severity=AuditIssueSeverity.HIGH,
                        text="el juez será sorteado mañana",
                        explanation="atribución sin claim/evidencia pertinente",
                        suggested_fix="retirar",
                        reason=AuditIssueReason.UNBACKED_MATERIAL,
                    )
                ],
            ),
            "ArticleDraft": plain_article_draft(article.headline, article.summary, article.body),
        }
    )
    result = AuditService(db_session, llm=llm, writer=llm).audit(event.id, trigger="test")
    assert result["passed"] is False
    assert PublishService(db_session).publish(event.id, trigger="test")["reason"] == "audit_not_passed"


def test_attributed_report_with_backing_can_pass(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(
        db_session,
        source.id,
        url="https://lnmas.test/ok",
        title="Bregman",
        body="Bregman dijo que es un vejestorio jurídico.",
        content_hash="ok1",
    )
    event = _event(db_session, item, title_internal="Bregman habló en el recinto")
    _claim(db_session, event, text="Bregman dijo que es un vejestorio jurídico", status=ClaimStatus.SINGLE_SOURCE)
    article = _draft_article(
        db_session,
        event,
        headline="Bregman criticó el régimen",
        summary="Según LN+, Bregman dijo que es un vejestorio jurídico.",
        body="Según LN+, Bregman dijo que es un vejestorio jurídico.",
    )
    persist_version_snapshot(db_session, event, article)
    result = AuditService(db_session, llm=_optimistic()).audit(event.id, trigger="test")
    assert result["passed"] is True
    assert PublishService(db_session).publish(event.id, trigger="test")["published"] is True


def test_bregman_effective_date_as_fact_blocked_when_llm_reports(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(db_session, source.id, url="https://ejemplo.test/b", title="Régimen", body="Bregman", content_hash="br1")
    event = _event(db_session, item, title_internal="Bregman criticó el régimen penal")
    _claim(db_session, event, text="Bregman dijo que el régimen entra en vigencia", status=ClaimStatus.SINGLE_SOURCE)
    article = _draft_article(
        db_session,
        event,
        headline="Régimen penal juvenil",
        summary="El nuevo régimen penal juvenil comenzó a regir.",
        body="El nuevo régimen penal juvenil comenzó a regir esta semana.",
    )
    persist_version_snapshot(db_session, event, article)
    llm = FakeStructuredLLM(
        {
            "ArticleAuditResult": ArticleAuditResult(
                passed=False,
                issues=[
                    AuditIssue(
                        type=AuditIssueType.UNSUPPORTED_CLAIM,
                        severity=AuditIssueSeverity.HIGH,
                        text="comenzó a regir",
                        explanation="vigencia afirmada como hecho",
                        suggested_fix="atribuir o retirar",
                        reason=AuditIssueReason.NORM_EFFECTIVE_AS_FACT,
                    )
                ],
            ),
            "ArticleDraft": plain_article_draft(article.headline, article.summary, article.body),
        }
    )
    result = AuditService(db_session, llm=llm, writer=llm).audit(event.id, trigger="test")
    assert result["passed"] is False
    assert PublishService(db_session).publish(event.id, trigger="test")["reason"] == "audit_not_passed"
