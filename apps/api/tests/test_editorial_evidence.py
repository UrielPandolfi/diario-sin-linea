from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.source_content import merge_item_metadata
from app.domain.enums import (
    ClaimImportance,
    ClaimStatus,
    EventSourceRelation,
    EvidenceType,
    IngestionMethod,
    PipelineStatus,
)
from app.models import Claim, ClaimEvidence, PipelineRun
from app.providers.base import SearchHit
from app.providers.fakes import FakeSearchProvider, FakeStructuredLLM, RecordingFetcher
from app.schemas import EventCreate, SourceCreate, SourceItemCreate
from app.schemas.claims import (
    ClaimExtractionBatch,
    ClaimResolutionBatch,
    ClaimResolutionItem,
    ExtractedClaim,
    ExtractedEvidence,
)
from app.schemas.editorial_evidence import CoverageMatch, PropositionRole, StatementEvidenceClass
from app.schemas.verification import (
    CheapClaimEvidenceAssessment,
    CheapEvidenceJudgement,
    EvidenceJudgementType,
    VerificationEvidence,
    VerificationResult,
    VerificationSubject,
    VerificationTarget,
)
from app.services.article_context import compact_verification
from app.services.claim_coverage import propositions_equivalent, salvage_excerpt, split_compound_extracted
from app.services.claim_service import CLAIM_STAGE, ClaimService
from app.services.editorial_label_policy import is_checked
from app.services.event_service import EventService
from app.services.information_origin import assess_origins, independent_support_count
from app.services.source_item_service import SourceItemService
from app.services.source_service import SourceService
from app.services.verification_outcome import (
    VERIFICATION_STAGE,
    compatible_verification_pair,
    pair_from_runs,
    verification_view_for_event,
)
from app.services.verification_plan import heuristic_plan, refine_plan
from app.services.verification_service import VerificationService
from app.services.writing_service import WritingService
from app.schemas.writing import ArticleDraft, ArticleDraftBlock, ArticleDraftSegment


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
    item = SourceItemService(session).ingest(
        SourceItemCreate(
            source_id=source_id,
            url=url,
            canonical_url=url,
            content_hash=content_hash,
            title=title,
            clean_text=body,
        )
    ).item
    merge_item_metadata(item, body_source="extracted_html", fetch_ok=True)
    session.flush()
    return item


def _event(session: Session, item, **overrides):
    payload = {
        "title_internal": "Presentaron una denuncia penal contra Alberto Fernández",
        "event_type": "judicial",
        "source_item_id": item.id,
        "started_at": datetime.now(timezone.utc),
        "locality": "Buenos Aires",
        "province": "CABA",
        "short_summary": "Una denuncia penal contra el ex presidente",
    }
    payload.update(overrides)
    return EventService(session).create(EventCreate(**payload))


def _extracted(*, text: str, claim_type: str, excerpt: str, **overrides) -> ExtractedClaim:
    payload = {
        "canonical_text": text,
        "claim_type": claim_type,
        "importance": ClaimImportance.HIGH,
        "subject": overrides.get("subject"),
        "predicate": overrides.get("predicate"),
        "object_text": overrides.get("object_text") or text,
        "evidence": [
            ExtractedEvidence(
                source_ref=1,
                evidence_type=EvidenceType.SUPPORTS,
                excerpt=excerpt,
                confidence=0.9,
            )
        ],
    }
    payload.update({key: value for key, value in overrides.items() if key not in payload})
    return ExtractedClaim(**payload)


def _resolution(*texts: str) -> ClaimResolutionBatch:
    return ClaimResolutionBatch(
        items=[
            ClaimResolutionItem(claim_ref=index, status=ClaimStatus.SINGLE_SOURCE, confidence=0.8)
            for index, _text in enumerate(texts, start=1)
        ]
    )


def test_split_bregman_compound_when_text_requires_it() -> None:
    raw = ExtractedClaim(
        canonical_text=(
            "Myriam Bregman dijo que el régimen se aplica a delitos graves y que entra en vigencia el mes próximo"
        ),
        claim_type="declaracion",
        importance=ClaimImportance.HIGH,
        subject="Bregman",
        evidence=[
            ExtractedEvidence(source_ref=1, evidence_type=EvidenceType.SUPPORTS, excerpt="entra en vigencia")
        ],
    )
    parts = split_compound_extracted(raw)
    kinds = {row.claim_type for row in parts}
    predicates = {row.predicate for row in parts}
    assert "declaracion" in kinds
    assert "dijo" in predicates
    assert "vigencia" in predicates or "alcance" in predicates
    assert len(parts) >= 2


def test_alberto_extractor_omission_recovers_denuncia_from_body(db_session: Session) -> None:
    source = _source(db_session)
    title = "Presentaron una denuncia penal contra Alberto Fernández por traición a la patria"
    body = (
        "El abogado presentó una denuncia penal contra Alberto Fernández por traición a la patria "
        "ante los tribunales federales. En otro tramo citó a los F-16 y un supuesto desfalco."
    )
    item = _item(db_session, source.id, url="https://medio.test/alberto", title=title, body=body, content_hash="alb1")
    event = _event(db_session, item, title_internal=title)
    llm = FakeStructuredLLM(
        {
            "ClaimExtractionBatch": ClaimExtractionBatch(
                claims=[
                    _extracted(
                        text="Alberto Fernández mencionó a los F-16",
                        claim_type="declaracion",
                        excerpt="citó a los F-16",
                        subject="Alberto Fernández",
                        predicate="dijo",
                    )
                ]
            ),
            "ClaimResolutionBatch": _resolution("a"),
        }
    )
    result = ClaimService(db_session, extractor_llm=llm, resolver_llm=llm).resolve(event.id, trigger="admin")
    texts = [claim.canonical_text.lower() for claim in db_session.scalars(select(Claim).where(Claim.event_id == event.id))]
    coverage = result["coverage"]
    assert coverage["coverage_gap"] is False or any("denuncia" in text for text in texts)
    assert any("denuncia" in text for text in texts)
    assert result["claims_fingerprint"]


def test_alberto_invalid_excerpt_without_body_act_keeps_gap(db_session: Session) -> None:
    source = _source(db_session)
    title = "Presentaron una denuncia penal contra Alberto Fernández por traición a la patria"
    body = "La nota reproduce citas sobre aviones F-16 y un supuesto desfalco en la gestión."
    item = _item(db_session, source.id, url="https://medio.test/alberto2", title=title, body=body, content_hash="alb2")
    event = _event(db_session, item, title_internal=title)
    llm = FakeStructuredLLM(
        {
            "ClaimExtractionBatch": ClaimExtractionBatch(
                claims=[
                    _extracted(
                        text="Alberto Fernández fue denunciado penalmente por traición a la patria",
                        claim_type="hecho",
                        excerpt="frase inventada que no está en el cuerpo",
                        predicate="denuncia",
                    )
                ]
            ),
            "ClaimResolutionBatch": ClaimResolutionBatch(items=[]),
        }
    )
    result = ClaimService(db_session, extractor_llm=llm, resolver_llm=llm).resolve(event.id, trigger="admin")
    coverage = result["coverage"]
    assert coverage["coverage_gap"] is True
    reasons = {row.get("gap_reason") for row in coverage["expected_central"]}
    assert reasons & {"recovery_failed", "dropped_invalid_excerpt", "not_extracted"}
    assert any(row.get("reason") == "invalid_excerpt" for row in coverage["dropped"])


def test_alberto_existence_is_not_guilt(db_session: Session) -> None:
    source = _source(db_session)
    title = "Presentaron una denuncia penal contra Alberto Fernández"
    body = (
        "El abogado presentó una denuncia penal contra Alberto Fernández por traición a la patria. "
        "Eso no prueba que el delito se haya cometido."
    )
    item = _item(db_session, source.id, url="https://medio.test/alberto3", title=title, body=body, content_hash="alb3")
    event = _event(db_session, item, title_internal=title)
    llm = FakeStructuredLLM(
        {
            "ClaimExtractionBatch": ClaimExtractionBatch(
                claims=[
                    _extracted(
                        text="Se presentó una denuncia penal contra Alberto Fernández por traición a la patria",
                        claim_type="hecho",
                        excerpt="presentó una denuncia penal contra Alberto Fernández",
                        predicate="denuncia",
                    )
                ]
            ),
            "ClaimResolutionBatch": _resolution("existencia"),
        }
    )
    result = ClaimService(db_session, extractor_llm=llm, resolver_llm=llm).resolve(event.id, trigger="admin")
    coverage = result["coverage"]
    roles = coverage.get("proposition_role") or {}
    assert "existence" in roles.values()
    assert "accusation_truth" not in roles.values()
    matched = [row for row in coverage["expected_central"] if row["match"] == CoverageMatch.EQUIVALENT.value]
    assert matched


def test_assessment_prompt_puts_claim_before_event_title(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(
        db_session,
        source.id,
        url="https://medio.test/cita",
        title="Denuncia",
        body="El ex presidente dijo que hubo un desfalco en la compra de aviones.",
        content_hash="cita1",
    )
    event = _event(db_session, item, title_internal="Presentaron una denuncia penal por traición a la patria")
    claim = Claim(
        event_id=event.id,
        canonical_text="Alberto Fernández dijo que hubo un desfalco en la compra de aviones",
        claim_type="declaracion",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.SINGLE_SOURCE,
        subject="Alberto Fernández",
        predicate="dijo",
    )
    db_session.add(claim)
    db_session.flush()
    from app.models import ClaimEvidence

    db_session.add(
        ClaimEvidence(
            claim_id=claim.id,
            source_item_id=item.id,
            evidence_type=EvidenceType.SUPPORTS,
            excerpt="dijo que hubo un desfalco",
            source_url=item.url,
        )
    )
    db_session.flush()
    assessor = FakeStructuredLLM(
        {
            "CheapClaimEvidenceAssessment": CheapClaimEvidenceAssessment(
                judgements=[
                    CheapEvidenceJudgement(
                        source_ref=1,
                        relation=EvidenceJudgementType.SUPPORTS,
                        excerpt="dijo que hubo un desfalco",
                    )
                ],
                ambiguous=False,
                reason="es una cita",
            )
        }
    )
    search = FakeSearchProvider([])
    VerificationService(
        db_session,
        llm=FakeStructuredLLM({"VerificationResult": VerificationResult(status=ClaimStatus.SINGLE_SOURCE, reason="ok")}),
        planner_llm=None,
        assessor_llm=assessor,
        search=search,
        fetcher=RecordingFetcher(),
    ).verify(event.id, trigger="admin")
    prompt = assessor.user_prompts[0]
    claim_at = prompt.find("canonical_text=")
    title_at = prompt.find("Presentaron una denuncia penal")
    assert claim_at != -1
    assert claim_at < title_at
    assert prompt.index("Claim a evaluar") < title_at


def test_bregman_split_selection_and_utterance_plan(db_session: Session) -> None:
    source = _source(db_session)
    body = (
        "Myriam Bregman dijo que el régimen se aplica a delitos graves y que entra en vigencia el mes próximo. "
        "La diputada afirmó que no alcanza a menores de 14 años."
    )
    item = _item(
        db_session,
        source.id,
        url="https://medio.test/bregman",
        title="Bregman criticó el régimen penal",
        body=body,
        content_hash="br1",
    )
    event = _event(
        db_session,
        item,
        title_internal="Bregman dijo que el régimen entra en vigencia y alcanza delitos graves",
    )
    mixed = (
        "Myriam Bregman dijo que el régimen se aplica a delitos graves y que entra en vigencia el mes próximo"
    )
    llm = FakeStructuredLLM(
        {
            "ClaimExtractionBatch": ClaimExtractionBatch(
                claims=[
                    _extracted(
                        text=mixed,
                        claim_type="declaracion",
                        excerpt="entra en vigencia el mes próximo",
                        subject="Bregman",
                        predicate="dijo",
                    )
                ]
            ),
            "ClaimResolutionBatch": ClaimResolutionBatch(
                items=[
                    ClaimResolutionItem(claim_ref=1, status=ClaimStatus.SINGLE_SOURCE, confidence=0.8),
                    ClaimResolutionItem(claim_ref=2, status=ClaimStatus.SINGLE_SOURCE, confidence=0.8),
                    ClaimResolutionItem(claim_ref=3, status=ClaimStatus.SINGLE_SOURCE, confidence=0.8),
                ]
            ),
        }
    )
    result = ClaimService(db_session, extractor_llm=llm, resolver_llm=llm).resolve(event.id, trigger="admin")
    claims = list(db_session.scalars(select(Claim).where(Claim.event_id == event.id)))
    assert len(claims) >= 2
    from app.services.verification_policy import select_claims
    from app.services.claim_coverage import CoverageContract

    coverage = CoverageContract.model_validate(result["coverage"])
    selected, skipped = select_claims(
        claims,
        flagged_ids=set(),
        limit=5,
        central_ids={claim.id for claim in claims},
    )
    assert not any(row.get("reason") == "veto" for row in skipped)
    utterance = next(
        (claim for claim in claims if (claim.predicate == "dijo" or claim.claim_type == "declaracion")),
        claims[0],
    )
    plan = heuristic_plan(utterance)
    refined = refine_plan(
        plan.model_copy(
            update={
                "verification_target": VerificationTarget.OFFICIAL_RECORD,
                "subject": VerificationSubject.LAW_OR_DECREE,
                "primary_source_required": True,
            }
        ),
        plan,
        claim=utterance,
    )
    assert refined.verification_target == VerificationTarget.PRIMARY_STATEMENT
    assert selected


def test_two_original_urls_same_informative_source_are_not_two_corroborations() -> None:
    from types import SimpleNamespace

    excerpt_a = "el ministerio informó que la medida entra en vigencia el lunes según el comunicado oficial publicado"
    excerpt_b = "según el mismo anuncio la medida entra en vigencia el lunes de acuerdo al texto del comunicado"
    claim = SimpleNamespace(
        canonical_text="La medida entra en vigencia el lunes",
        claim_type="documento",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.SINGLE_SOURCE,
        subject=None,
        evidence=[
            SimpleNamespace(
                evidence_type=EvidenceType.SUPPORTS,
                excerpt=excerpt_a,
                source_item=SimpleNamespace(
                    clean_text=f"{excerpt_a} https://seguridad.gob.ar/comunicado-unico",
                    canonical_url="https://portal.gob.ar/nota-a",
                    url="https://portal.gob.ar/nota-a",
                    title="A",
                    source=None,
                    metadata_json={"body_source": "extracted_html"},
                ),
                source_url="https://portal.gob.ar/nota-a",
            ),
            SimpleNamespace(
                evidence_type=EvidenceType.SUPPORTS,
                excerpt=excerpt_b,
                source_item=SimpleNamespace(
                    clean_text=f"{excerpt_b} https://seguridad.gob.ar/comunicado-unico",
                    canonical_url="https://otro.gob.ar/nota-b",
                    url="https://otro.gob.ar/nota-b",
                    title="B",
                    source=None,
                    metadata_json={"body_source": "extracted_html"},
                ),
                source_url="https://otro.gob.ar/nota-b",
            ),
        ],
    )
    assessment = assess_origins(claim)
    assert assessment.known_independent == 1
    assert independent_support_count(claim) == 1
    from app.services.claim_service import clamp_supported_status

    assert clamp_supported_status(claim, ClaimStatus.SUPPORTED) == ClaimStatus.SINGLE_SOURCE


def test_three_unknown_documents_do_not_count_as_independent() -> None:
    from types import SimpleNamespace

    rows = []
    for index in range(3):
        rows.append(
            SimpleNamespace(
                evidence_type=EvidenceType.SUPPORTS,
                excerpt=f"version {index} con heridos en el choque según testigos locales distintos",
                source_item=SimpleNamespace(
                    clean_text=f"version {index} con heridos en el choque según testigos locales distintos",
                    canonical_url=f"https://medio{index}.test/n",
                    url=f"https://medio{index}.test/n",
                    title=str(index),
                    source=None,
                    metadata_json={"body_source": "extracted_html"},
                ),
                source_url=f"https://medio{index}.test/n",
            )
        )
    claim = SimpleNamespace(
        canonical_text="Hubo seis heridos",
        claim_type="hecho",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.SINGLE_SOURCE,
        subject=None,
        evidence=rows,
    )
    assessment = assess_origins(claim)
    assert assessment.known_independent == 0
    assert assessment.unknown_groups == 3
    from app.services.claim_service import clamp_supported_status

    assert clamp_supported_status(claim, ClaimStatus.SUPPORTED) == ClaimStatus.SINGLE_SOURCE


def test_new_extract_plus_failed_verify_does_not_reuse_prior_approval(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(
        db_session,
        source.id,
        url="https://medio.test/par",
        title="Choque",
        body="Un colectivo chocó en Rosario y dejó heridos según testigos.",
        content_hash="par1",
    )
    event = _event(db_session, item, title_internal="Choque en Rosario")
    first = FakeStructuredLLM(
        {
            "ClaimExtractionBatch": ClaimExtractionBatch(
                claims=[
                    _extracted(
                        text="Un colectivo chocó en Rosario",
                        claim_type="hecho",
                        excerpt="Un colectivo chocó en Rosario",
                    )
                ]
            ),
            "ClaimResolutionBatch": _resolution("choque"),
        }
    )
    ClaimService(db_session, extractor_llm=first, resolver_llm=first).resolve(event.id, trigger="admin")
    claim = db_session.scalars(select(Claim).where(Claim.event_id == event.id)).one()
    claim_run = db_session.scalars(
        select(PipelineRun).where(PipelineRun.event_id == event.id, PipelineRun.stage == CLAIM_STAGE)
    ).one()
    fingerprint = (claim_run.metadata_json or {}).get("claims_fingerprint")
    db_session.add(
        PipelineRun(
            event_id=event.id,
            stage=VERIFICATION_STAGE,
            status=PipelineStatus.SUCCESS,
            finished_at=datetime.now(timezone.utc),
            metadata_json={
                "claims_fingerprint": fingerprint,
                "based_on_claim_run_id": str(claim_run.id),
                "selected": [{"claim_id": str(claim.id)}],
                "primary_source_supports_claim": {str(claim.id): True},
                "sol": [
                    {
                        "claim_id": str(claim.id),
                        "status_after": "SUPPORTED",
                        "unresolved": False,
                        "reason": "aprobado",
                    }
                ],
            },
        )
    )
    db_session.flush()
    second = FakeStructuredLLM(
        {
            "ClaimExtractionBatch": ClaimExtractionBatch(
                claims=[
                    _extracted(
                        text="El choque dejó cuatro heridos",
                        claim_type="cifra",
                        excerpt="dejó heridos",
                        predicate="heridos",
                        object_text="4",
                    )
                ]
            ),
            "ClaimResolutionBatch": _resolution("heridos"),
        }
    )
    ClaimService(db_session, extractor_llm=second, resolver_llm=second).resolve(event.id, trigger="admin")
    db_session.add(
        PipelineRun(
            event_id=event.id,
            stage=VERIFICATION_STAGE,
            status=PipelineStatus.FAILED,
            error_message="boom",
            finished_at=datetime.now(timezone.utc),
            metadata_json={},
        )
    )
    db_session.flush()
    pair_claim, pair_verify = compatible_verification_pair(db_session, event.id)
    assert pair_claim is not None
    assert pair_verify is None
    _run, view = verification_view_for_event(db_session, event.id)
    assert view.sol_by_id == {}
    assert is_checked(claim, view) is False
    runs = list(
        db_session.scalars(
            select(PipelineRun)
            .where(PipelineRun.event_id == event.id)
            .order_by(PipelineRun.started_at.desc())
        )
    )
    compact = compact_verification(pair_from_runs(runs)[1])
    assert compact.sol == []
    draft = ArticleDraft(
        headline="Choque",
        summary="Hubo un choque.",
        body_blocks=[
            ArticleDraftBlock(segments=[ArticleDraftSegment(text="Hubo un choque en Rosario.", claim_refs=["C1"])])
        ],
    )
    written = WritingService(db_session, llm=FakeStructuredLLM({"ArticleDraft": draft})).write(
        event.id, trigger="admin"
    )
    if written.get("written"):
        assert written.get("verification_run_id") is None
        assert written.get("stale_verification") is True


def test_video_search_hit_only_is_not_authentic_primary(db_session: Session) -> None:
    source = _source(db_session, is_monitored=False, domain="youtube.com")
    item = _item(
        db_session,
        source.id,
        url="https://www.youtube.com/watch?v=abcdefghijk",
        title="Discurso",
        body="Bregman",
        content_hash="yt1",
    )
    merge_item_metadata(item, body_source="search_snippet", fetch_ok=False)
    event = _event(db_session, item, title_internal="Bregman dio una conferencia")
    claim = Claim(
        event_id=event.id,
        canonical_text="Bregman dijo que es un vejestorio jurídico",
        claim_type="declaracion",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.SINGLE_SOURCE,
        subject="Bregman",
        predicate="dijo",
    )
    db_session.add(claim)
    db_session.flush()
    from app.models import ClaimEvidence

    db_session.add(
        ClaimEvidence(
            claim_id=claim.id,
            source_item_id=item.id,
            evidence_type=EvidenceType.SUPPORTS,
            excerpt="Bregman",
            source_url=item.url,
        )
    )
    db_session.flush()
    assessment = assess_origins(claim)
    assert assessment.statement_evidence_class in {
        StatementEvidenceClass.SEARCH_HIT_ONLY,
        StatementEvidenceClass.ACCESS_LIMITED,
    }
    from app.services.claim_service import clamp_supported_status

    assert clamp_supported_status(claim, ClaimStatus.SUPPORTED) != ClaimStatus.SUPPORTED or (
        assessment.statement_evidence_class == StatementEvidenceClass.AUTHENTIC_PRIMARY
    )
    assert clamp_supported_status(claim, ClaimStatus.SUPPORTED) == ClaimStatus.SINGLE_SOURCE


def test_extracted_transcript_supports_utterance_not_content(db_session: Session) -> None:
    source = _source(db_session, is_monitored=False, domain="hcdn.gob.ar", name="Diputados")
    body = (
        "Versión taquigráfica. Diputada Myriam Bregman: es un vejestorio jurídico que no se aplica a menores. "
        "Fin de la transcripción del dicho en el recinto."
    )
    item = _item(
        db_session,
        source.id,
        url="https://www.hcdn.gob.ar/transcript/bregman",
        title="Versión taquigráfica Bregman",
        body=body,
        content_hash="tr1",
    )
    event = _event(db_session, item, title_internal="Bregman habló en el recinto")
    claim = Claim(
        event_id=event.id,
        canonical_text="Myriam Bregman dijo que es un vejestorio jurídico",
        claim_type="declaracion",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.SINGLE_SOURCE,
        subject="Bregman",
        predicate="dijo",
    )
    db_session.add(claim)
    db_session.flush()
    from app.models import ClaimEvidence

    db_session.add(
        ClaimEvidence(
            claim_id=claim.id,
            source_item_id=item.id,
            evidence_type=EvidenceType.SUPPORTS,
            excerpt="es un vejestorio jurídico que no se aplica a menores",
            source_url=item.url,
        )
    )
    db_session.flush()
    db_session.refresh(claim)
    assessment = assess_origins(claim)
    assert assessment.statement_evidence_class == StatementEvidenceClass.AUTHENTIC_PRIMARY
    from app.services.claim_service import clamp_supported_status

    assert clamp_supported_status(claim, ClaimStatus.SUPPORTED) == ClaimStatus.SUPPORTED


def test_sol_optimistic_keeps_policy_reason_and_resolved_false(db_session: Session) -> None:
    source_a = _source(db_session, name="A", domain="medio-a.test", feed_url="https://medio-a.test/rss.xml")
    source_b = _source(db_session, name="B", domain="medio-b.test", feed_url="https://medio-b.test/rss.xml")
    body = "Vital presentó una denuncia penal contra Federman según pudo saber este medio."
    item_a = _item(db_session, source_a.id, url="https://medio-a.test/n", title="A", body=body, content_hash="sa")
    item_b = _item(db_session, source_b.id, url="https://medio-b.test/n", title="B", body=body, content_hash="sb")
    event = _event(db_session, item_a, title_internal="Denuncia de Vital")
    EventService(db_session).attach_source(event, item_b.id, relation_type=EventSourceRelation.ADDITIONAL)
    claim = Claim(
        event_id=event.id,
        canonical_text="Víctor Eduardo Vital presentó una denuncia penal contra Natalia Laura Federman",
        claim_type="hecho",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.SINGLE_SOURCE,
    )
    db_session.add(claim)
    db_session.flush()
    from app.models import ClaimEvidence

    for item in (item_a, item_b):
        db_session.add(
            ClaimEvidence(
                claim_id=claim.id,
                source_item_id=item.id,
                evidence_type=EvidenceType.SUPPORTS,
                excerpt="presentó una denuncia penal",
                source_url=item.url,
            )
        )
    db_session.flush()
    sol = FakeStructuredLLM(
        {
            "VerificationResult": VerificationResult(
                status=ClaimStatus.SUPPORTED,
                reason="varias fuentes independientes confirman la denuncia",
                unresolved=False,
                evidence=[],
            )
        }
    )
    result = VerificationService(
        db_session, llm=sol, search=FakeSearchProvider([]), fetcher=RecordingFetcher()
    ).verify(event.id, trigger="admin")
    db_session.refresh(claim)
    assert claim.status == ClaimStatus.SINGLE_SOURCE
    cid = str(claim.id)
    sol_row = next(row for row in result["sol"] if row["claim_id"] == cid)
    assert sol_row["unresolved"] is False
    assert sol_row["llm_reason"] == "varias fuentes independientes confirman la denuncia"
    assert "independiente" in (sol_row["reason"] or "").lower() or "primaria" in (sol_row["reason"] or "").lower() or "certeza" in (sol_row["reason"] or "").lower() or "origen" in (sol_row["reason"] or "").lower()
    decision = result["decision_by_claim_id"][cid]
    assert decision["unresolved"] is False
    assert decision["llm_reason"] == sol_row["llm_reason"]
    assert decision["status"] == ClaimStatus.SINGLE_SOURCE.value
    from app.services.claim_card_presentation import (
        contains_llm_reason,
        contradicts_single_source_independence,
        presentation_for_claim,
    )
    from app.services.feed_ranking import compact_public_claims
    from app.services.verification_outcome import verification_view_for_event

    _run, view = verification_view_for_event(db_session, event.id)
    card = presentation_for_claim(claim, view)
    assert contradicts_single_source_independence(claim.status.value, card) is False
    assert card.verification_label != "Corroborado"
    rows = compact_public_claims(db_session, event)
    assert not contains_llm_reason(rows)
    assert (rows[0].get("verification") or {}).get("reason") is None


def test_attributed_report_is_not_authentic_primary() -> None:
    from types import SimpleNamespace

    claim = SimpleNamespace(
        canonical_text="Bregman dijo que es un vejestorio jurídico",
        claim_type="declaracion",
        subject="Bregman",
        predicate="dijo",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.SINGLE_SOURCE,
        evidence=[
            SimpleNamespace(
                evidence_type=EvidenceType.SUPPORTS,
                excerpt="Bregman afirmó que es un vejestorio jurídico en conferencia de prensa",
                source_item=SimpleNamespace(
                    clean_text="La diputada Bregman afirmó que es un vejestorio jurídico en conferencia de prensa",
                    canonical_url="https://diario.test/nota",
                    url="https://diario.test/nota",
                    title="Bregman habló",
                    source=SimpleNamespace(is_monitored=True, domain="diario.test"),
                    metadata_json={"body_source": "extracted_html", "fetch_ok": True},
                ),
                source_url="https://diario.test/nota",
            )
        ],
    )
    assessment = assess_origins(claim)
    assert assessment.statement_evidence_class == StatementEvidenceClass.ATTRIBUTED_REPORT
    from app.services.claim_service import clamp_supported_status

    assert clamp_supported_status(claim, ClaimStatus.SUPPORTED) == ClaimStatus.SINGLE_SOURCE


def test_split_judge_ruling_from_utterance() -> None:
    raw = ExtractedClaim(
        canonical_text=(
            "La jueza María Servini suspendió la Ley 27.801 y dijo: "
            "«Esta norma es inconstitucional»"
        ),
        claim_type="hecho",
        importance=ClaimImportance.HIGH,
        subject="Servini",
        evidence=[
            ExtractedEvidence(source_ref=1, evidence_type=EvidenceType.SUPPORTS, excerpt="suspendió la Ley")
        ],
    )
    parts = split_compound_extracted(raw)
    assert len(parts) >= 2
    predicados = {row.predicate for row in parts}
    assert "dijo" in predicados
    assert "resolucion" in predicados
    ruling = next(row for row in parts if row.predicate == "resolucion")
    said = next(row for row in parts if row.predicate == "dijo")
    assert "suspend" in ruling.canonical_text.lower()
    assert "inconstitucional" in said.canonical_text.lower()
    assert "dijo" not in ruling.canonical_text.lower()


def test_judge_utterance_is_not_covered_by_ruling() -> None:
    ruling = "La jueza María Servini suspendió la Ley 27.801 de reiterancia"
    said = "La jueza María Servini dijo: «Esta norma es inconstitucional»"
    assert propositions_equivalent(said, ruling) == CoverageMatch.NONE
    assert propositions_equivalent(ruling, said) == CoverageMatch.NONE


def test_salvage_excerpt_requires_literal_body_fragment() -> None:
    body = (
        "La jueza María Servini hizo lugar a un amparo y suspendió la Ley 27.801. "
        "«Esta norma es inconstitucional», afirmó la magistrada."
    )
    found = salvage_excerpt("Servini dijo: «Esta norma es inconstitucional»", body)
    assert found is not None
    assert "inconstitucional" in found.lower()
    assert found in body
    assert salvage_excerpt("Hubo doce muertos en el acto", body) is None


def test_judge_utterance_kept_when_excerpt_is_in_body(db_session: Session) -> None:
    source = _source(db_session)
    title = "Una jueza suspendió la Ley 27.801 y dijo: «Esta norma es inconstitucional»"
    quote = "«Esta norma es inconstitucional»"
    body = (
        "La jueza federal María Servini hizo lugar a un amparo y suspendió la Ley 27.801 de reiterancia. "
        f"{quote}, afirmó la magistrada al leer los fundamentos. "
        "La decisión no está firme."
    )
    item = _item(db_session, source.id, url="https://medio.test/jueza", title=title, body=body, content_hash="j1")
    event = _event(
        db_session,
        item,
        title_internal=title,
        event_type="judicial",
        short_summary="Una jueza suspendió la Ley 27.801",
    )
    llm = FakeStructuredLLM(
        {
            "ClaimExtractionBatch": ClaimExtractionBatch(
                claims=[
                    _extracted(
                        text=(
                            "La jueza María Servini suspendió la Ley 27.801 y dijo que "
                            "la norma es inconstitucional"
                        ),
                        claim_type="hecho",
                        excerpt="la jueza kirchnerista fulminó la polémica ley",
                        subject="Servini",
                        predicate="resolvio",
                    )
                ]
            ),
            "ClaimResolutionBatch": _resolution("resolucion", "dicho"),
        }
    )
    result = ClaimService(db_session, extractor_llm=llm, resolver_llm=llm).resolve(event.id, trigger="admin")
    claims = list(db_session.scalars(select(Claim).where(Claim.event_id == event.id)))
    texts = [claim.canonical_text.lower() for claim in claims]
    assert any("inconstitucional" in text and "dijo" in text for text in texts)
    assert any("suspend" in text for text in texts)
    utterance = next(
        claim
        for claim in claims
        if "inconstitucional" in claim.canonical_text.lower() and "dijo" in claim.canonical_text.lower()
    )
    excerpts = [
        row.excerpt or ""
        for row in db_session.scalars(select(ClaimEvidence).where(ClaimEvidence.claim_id == utterance.id))
    ]
    assert excerpts
    assert any(excerpt and excerpt in body for excerpt in excerpts)
    coverage = result["coverage"]
    utterance_expected = [
        row
        for row in coverage["expected_central"]
        if row.get("act") == "utterance" or "inconstitucional" in (row.get("proposition") or "").lower()
    ]
    assert utterance_expected
    assert all(row.get("match") == CoverageMatch.EQUIVALENT.value for row in utterance_expected)
    assert coverage["coverage_gap"] is False
    assert {claim.status for claim in claims} == {ClaimStatus.SINGLE_SOURCE}


def test_judge_utterance_coverage_gap_without_body_excerpt(db_session: Session) -> None:
    source = _source(db_session)
    title = "Una jueza suspendió la Ley 27.801 y dijo: «Esta norma es inconstitucional»"
    body = (
        "La jueza federal María Servini hizo lugar a un amparo y suspendió la Ley 27.801 de reiterancia. "
        "La decisión no está firme."
    )
    item = _item(db_session, source.id, url="https://medio.test/jueza2", title=title, body=body, content_hash="j2")
    event = _event(
        db_session,
        item,
        title_internal=title,
        event_type="judicial",
        short_summary="Una jueza suspendió la Ley 27.801",
    )
    llm = FakeStructuredLLM(
        {
            "ClaimExtractionBatch": ClaimExtractionBatch(
                claims=[
                    _extracted(
                        text="La jueza María Servini suspendió la Ley 27.801 de reiterancia",
                        claim_type="hecho",
                        excerpt="suspendió la Ley 27.801 de reiterancia",
                        subject="Servini",
                        predicate="resolucion",
                    )
                ]
            ),
            "ClaimResolutionBatch": _resolution("resolucion"),
        }
    )
    result = ClaimService(db_session, extractor_llm=llm, resolver_llm=llm).resolve(event.id, trigger="admin")
    claims = list(db_session.scalars(select(Claim).where(Claim.event_id == event.id)))
    coverage = result["coverage"]
    assert coverage["coverage_gap"] is True
    utterance_expected = [
        row
        for row in coverage["expected_central"]
        if row.get("act") == "utterance" or "inconstitucional" in (row.get("proposition") or "").lower()
    ]
    assert utterance_expected
    assert all(row.get("match") != CoverageMatch.EQUIVALENT.value for row in utterance_expected)
    assert not any(
        "inconstitucional" in claim.canonical_text.lower() and "dijo" in claim.canonical_text.lower()
        for claim in claims
    )
    assert {claim.status for claim in claims} <= {ClaimStatus.SINGLE_SOURCE}
