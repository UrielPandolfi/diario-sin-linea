import json
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import select

from app.core.article_body import annotated_article_draft
from app.domain.enums import ClaimStatus, EvidenceType, PipelineStatus
from app.models import Article, ArticleVersion, PipelineRun
from app.providers.fakes import FakeStructuredLLM, FakeSearchProvider
from app.schemas.auditing import ArticleAuditResult, AuditIssue, AuditIssueType, AuditIssueSeverity, AuditIssueReason
from app.schemas.claims import ClaimExtractionBatch, ClaimResolutionBatch, ExtractedEvidence
from app.schemas.editorial_evidence import SupportBasis
from app.schemas.verification import VerificationResult, VerificationEvidence
from app.schemas.writing import ArticleContext, ContextSupportBasis
from app.services.article_context import build_article_context, compact_verification
from app.services.audit_service import AuditService
from app.services.writing_service import WritingService
from app.services.material_change import detect_material_change
from tests.test_claims import _source, _item, _event, _attach, _llm, _service, _event_claims
from tests.test_material_attribution import extracted_pair
from tests.test_verification import _service as verification_service

CASE = json.loads((Path(__file__).parent / "fixtures" / "material_normas.json").read_text(encoding="utf-8"))


def test_context_support_basis_roundtrips_all_fields_and_old_snapshots():
    basis = SupportBasis(documents_consulted=6, documents_supporting=3, documents_qualifying=1,
                         documents_contradicting=1, known_independent_count=0, unknown_group_count=1,
                         reprint_collapsed_count=2, primary_access="found_unrelated",
                         demotion="missing_documentary_primary", document_keys=["a", "b", "c"],
                         information_origins=[], evaluated_canonical_text=CASE["fact"])
    run = SimpleNamespace(id="verify", status=PipelineStatus.SUCCESS, metadata_json={
        "decision_by_claim_id": {"claim": {"claim_id": "claim", "status": "CONFLICTING", "support_basis": basis.model_dump()}}
    })
    compact = compact_verification(run)
    transported = compact.decision_by_claim_id["claim"].support_basis
    assert transported.model_dump() == basis.model_dump()
    assert ContextSupportBasis.model_validate({"known_independent_count": 0, "demotion": None}).documents_supporting == 0


def test_material_evidence_change_triggers_writing_without_status_change():
    before = {"id": "a", "status": "SINGLE_SOURCE", "importance": "MEDIUM", "evidence_posture": {"documents_supporting": 1}}
    after = {**before, "evidence_posture": {"documents_supporting": 3}}
    assert detect_material_change([before], [after]).reasons == ["evidence_posture_changed"]
    assert not detect_material_change([before], [after]).is_material
    assert not detect_material_change([after], [after]).is_material


def _resolve_case(session):
    source = _source(session)
    items = [_item(session, source.id, url=url, title="Reformas", body=CASE["statement"], content_hash=url)
             for url in CASE["reports"]]
    event = _event(session, items[0], title_internal="Milei habló de reformas", short_summary=CASE["statement"])
    for item in items[1:]:
        _attach(session, event, item)
    raw = extracted_pair()
    raw.evidence = [ExtractedEvidence(source_ref=i, evidence_type=EvidenceType.SUPPORTS, excerpt=CASE["statement"]) for i in (1, 2, 3)]
    extraction = _service(session, _llm(ClaimExtractionBatch(claims=[raw]), ClaimResolutionBatch())).resolve(event.id, trigger="test")
    assert "error" not in extraction
    llm = FakeStructuredLLM({"VerificationResult": VerificationResult(status=ClaimStatus.SUPPORTED,
        evidence=[VerificationEvidence(source_ref=i, evidence_type=EvidenceType.SUPPORTS, excerpt=CASE["statement"]) for i in (1, 2, 3)])})
    verification = verification_service(session, llm, FakeSearchProvider()).verify(event.id, trigger="test")
    assert "error" not in verification
    session.expire(event, ["claims"])
    runs = list(session.scalars(select(PipelineRun).where(PipelineRun.event_id == event.id).order_by(PipelineRun.started_at.desc())))
    context = build_article_context(event, pipeline_runs=runs)
    return event, context, verification


def test_milei_writing_snapshot_and_audit_rewrite_use_the_same_evidence(db_session):
    event, context, verification = _resolve_case(db_session)
    claims = context.single_source_claims
    assert len(claims) == 2
    factual = next(c for c in claims if c.claim_type == "cifra")
    statement = next(c for c in claims if c.claim_type == "declaracion")
    assert factual.id in statement.related_claim_ids and statement.id in factual.related_claim_ids
    assert factual.support_basis.documents_supporting == 3
    assert factual.support_basis.known_independent_count <= 1
    assert factual.support_basis.primary_access == "not_found"
    bad = annotated_article_draft("Milei habló de reformas", "El presidente explicó su agenda.", [[(CASE["fact"], [factual.ref])]])
    writer = FakeStructuredLLM({"ArticleDraft": bad})
    written = WritingService(db_session, llm=writer).write(event.id, trigger="test")
    assert written["written"] is True
    payload = json.loads(writer.user_prompts[0][writer.user_prompts[0].find("{"):])
    sent = next(c for c in payload["single_source_claims"] if c["id"] == factual.id)
    assert sent["support_basis"] == factual.support_basis.model_dump()
    assert ArticleContext.model_validate(written["evidence_snapshot"]["article_context"]).single_source_claims
    # New DB information must not silently change the posture for this version.
    db_session.get(type(event.claims[0]), factual.id).status = ClaimStatus.SUPPORTED
    db_session.flush()
    issue = AuditIssue(type=AuditIssueType.UNSUPPORTED_CLAIM, severity=AuditIssueSeverity.MEDIUM,
                       text=CASE["fact"], explanation="El snapshot solo tiene reportes, sin primaria ni independencia acreditada.",
                       reason=AuditIssueReason.SINGLE_AS_CORROBORATED, claim_id=factual.id, claim_ref=factual.ref)
    good = annotated_article_draft("Milei habló de reformas", "El presidente explicó su agenda.",
                                    [[(CASE["attributed_with_limitation"], [statement.ref, factual.ref])]])
    auditor = FakeStructuredLLM({"ArticleAuditResult": [ArticleAuditResult(passed=True, issues=[issue]), ArticleAuditResult(passed=True)]})
    rewriter = FakeStructuredLLM({"ArticleDraft": good})
    audited = AuditService(db_session, llm=auditor, writer=rewriter).audit(event.id, trigger="test")
    assert audited["passed"] is False
    assert audited["reason"] == "structural_block"
    assert audited["rewrite_count"] == 0
    assert rewriter.calls == []
    audit_payload = json.loads(auditor.user_prompts[0].split("\n", 1)[1])
    audited_fact = next(c for c in audit_payload["evidence_posture"] if c["claim_id"] == factual.id)
    assert audited_fact["status"] == "SINGLE_SOURCE"
    assert audited_fact["support_basis"]["documents_supporting"] == 3
    assert "document_keys" not in audited_fact["support_basis"]
    assert "source_contexts" not in audit_payload
    article = db_session.scalars(select(Article).where(Article.event_id == event.id)).one()
    assert CASE["fact"] in (article.body or "")
    assert len(list(db_session.scalars(select(ArticleVersion).where(ArticleVersion.article_id == article.id)))) == 1
    assert len(list(db_session.scalars(select(PipelineRun).where(PipelineRun.event_id == event.id)))) >= 4
