"""C8: acto verificable vs caracterización/consecuencia. Dobles, sin LLM real."""
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.domain.enums import ClaimImportance, ClaimStatus, EventSourceRelation, EvidenceType
from app.main import app
from app.models import Claim, ClaimEvidence
from app.providers.fakes import FakeSearchProvider, FakeStructuredLLM
from app.schemas.claims import (
    ClaimExtractionBatch,
    ClaimResolutionBatch,
    ClaimResolutionItem,
    ExtractedClaim,
    ExtractedEvidence,
    ExtractedProposition,
)
from app.schemas.editorial_evidence import (
    CoverageMatch,
    Demotion,
    PropositionRole,
    StatementEvidenceClass,
)
from app.schemas.writing import ContextClaimDecision
from app.services.article_service import ArticleService
from app.services.claim_coverage import (
    expected_centrals_from_event,
    is_mixed_proposition,
    proposition_role_for,
    split_compound_extracted,
)
from app.services.claim_meaning import split_attributed_content
from app.services.claim_service import ClaimService, clamp_supported_status, comparison_key_for
from app.services.evidence_comparison import conflict_comparability
from app.services.event_service import EventService
from app.services.feed_ranking import compact_public_claims
from app.services.information_origin import assess_origins, classify_statement_row, demotion_for
from app.services.material_change import detect_material_change, snapshot_claims
from app.services.publish_service import PublishService
from app.services.verification_plan import apply_primary_requirement, heuristic_plan
from app.services.verification_policy import requires_authoritative_source, select_claims
from app.services.verification_service import VerificationService
from app.schemas import ArticleCreate
from tests.editorial_snapshot import persist_version_snapshot
from tests.test_audit import _pass_audit
from tests.test_editorial_evidence import _event, _extracted, _item, _resolution, _source
from tests.test_independent_reporting import _claim as _origin_claim, _row
from tests.test_verification import _claim as _db_claim, _evidence as _db_evidence, _service as _verify_service, _sol
from tests.test_writing_certainty import _audit


ACT_REACTION = "Milei publicó un mensaje y generó polémica"
PUBLICATION_EXCERPT = "Milei publicó un mensaje: bajaré impuestos"
REACTION_EXCERPT = "El anuncio generó polémica en el Congreso y en redes"
QUALIFIED = "Milei calificó la medida de polémica"
QUOTED = 'Milei dijo: "La medida es polémica"'
AMBIGUOUS = "Milei publicó un mensaje que generó polémica"
SIMPLE_UTTERANCE = "Myriam Bregman dijo que es un vejestorio jurídico"
BREGMAN = (
    "Myriam Bregman dijo que el régimen se aplica a delitos graves y que entra en vigencia el mes próximo"
)
NEGATED = "Milei no publicó un mensaje ayer y no generó polémica"
MODAL_FIGURE = (
    "Milei habría publicado 3 mensajes el 2 de marzo y generó polémica"
)


def _raw(text: str, *, excerpt: str, claim_type: str = "declaracion", **overrides) -> ExtractedClaim:
    evidence = overrides.pop(
        "evidence",
        [
            ExtractedEvidence(
                source_ref=1,
                evidence_type=EvidenceType.SUPPORTS,
                excerpt=excerpt,
                confidence=0.9,
            )
        ],
    )
    payload = dict(
        canonical_text=text,
        claim_type=claim_type,
        importance=ClaimImportance.HIGH,
        subject=overrides.pop("subject", "Milei"),
        predicate=overrides.pop("predicate", "dijo"),
        object_text=overrides.pop("object_text", text),
        evidence=evidence,
    )
    payload.update(overrides)
    return ExtractedClaim(**payload)


def _authentic_row(
    *,
    body: str,
    excerpt: str,
    url: str = "https://www.hcdn.gob.ar/transcript/c8",
    domain: str = "hcdn.gob.ar",
):
    return _row(
        url=url,
        excerpt=excerpt,
        body=body,
        domain=domain,
        source_id=uuid4(),
    )


def test_act_plus_reaction_is_mixed_and_splits_unequivocal_coordination():
    assert is_mixed_proposition(ACT_REACTION, "declaracion") is True
    parts = split_compound_extracted(_raw(ACT_REACTION, excerpt=PUBLICATION_EXCERPT))
    assert len(parts) == 2
    publication = next(part for part in parts if "public" in (part.canonical_text or "").lower())
    reaction = next(part for part in parts if part.predicate == "reaccion")
    assert "generó polémica" not in publication.canonical_text
    assert "Milei" in (reaction.canonical_text or "")
    assert "generó polémica" in (reaction.canonical_text or "")
    assert proposition_role_for(publication) == PropositionRole.UTTERANCE
    assert is_mixed_proposition(publication.canonical_text, publication.claim_type) is False
    assert proposition_role_for(reaction) != PropositionRole.UTTERANCE
    assert all(ev.source_ref == 1 for ev in publication.evidence)
    assert all(ev.source_ref == 1 for ev in reaction.evidence)
    assert any(ev.evidence_type == EvidenceType.SUPPORTS for ev in publication.evidence)
    assert all(ev.evidence_type != EvidenceType.SUPPORTS for ev in reaction.evidence)


def test_quoted_and_qualifying_characterization_are_not_split():
    assert is_mixed_proposition(QUALIFIED, "declaracion") is False
    assert is_mixed_proposition(QUOTED, "declaracion") is False
    assert len(split_compound_extracted(_raw(QUALIFIED, excerpt=QUALIFIED))) == 1
    assert len(split_compound_extracted(_raw(QUOTED, excerpt=QUOTED))) == 1
    assert proposition_role_for(QUALIFIED, "declaracion") == PropositionRole.UTTERANCE
    assert proposition_role_for(QUOTED, "declaracion") == PropositionRole.UTTERANCE


def test_adjective_or_conjunction_without_two_propositions_does_not_split():
    adjective = "Milei publicó la polémica medida"
    conjunction = "Milei publicó un mensaje y un video"
    assert is_mixed_proposition(adjective, "declaracion") is False
    assert is_mixed_proposition(conjunction, "hecho") is False
    assert len(split_compound_extracted(_raw(adjective, excerpt=adjective))) == 1
    assert len(split_compound_extracted(_raw(conjunction, excerpt=conjunction, claim_type="hecho"))) == 1


def test_ambiguous_relative_clause_stays_mixed_and_blocks_authentic_primary():
    assert is_mixed_proposition(AMBIGUOUS, "declaracion") is True
    parts = split_compound_extracted(_raw(AMBIGUOUS, excerpt=PUBLICATION_EXCERPT))
    assert len(parts) == 1
    assert parts[0].canonical_text == AMBIGUOUS
    assert proposition_role_for(AMBIGUOUS, "declaracion") == PropositionRole.OTHER
    body = (
        f"{AMBIGUOUS}. {PUBLICATION_EXCERPT}. "
        "La captura reproduce el texto original de la publicación en la cuenta verificada."
    )
    row = _authentic_row(body=body, excerpt=PUBLICATION_EXCERPT)
    claim = _origin_claim(
        text=AMBIGUOUS,
        claim_type="declaracion",
        subject="Milei",
        predicate="publico",
        evidence=[row],
    )
    assert classify_statement_row(claim, row) != StatementEvidenceClass.AUTHENTIC_PRIMARY
    assessment = assess_origins(claim)
    assert assessment.statement_evidence_class != StatementEvidenceClass.AUTHENTIC_PRIMARY
    assert requires_authoritative_source(claim) is True
    plan = heuristic_plan(claim)
    status = apply_primary_requirement(claim, ClaimStatus.SUPPORTED, plan, primary_supports=False)
    assert status != ClaimStatus.SUPPORTED
    assert clamp_supported_status(claim, ClaimStatus.SUPPORTED) != ClaimStatus.SUPPORTED
    assert demotion_for(
        desired_status="SUPPORTED",
        final_status=status.value,
        assessment=assessment,
        primary_required=True,
        primary_supports=False,
        mixed=True,
        role=PropositionRole.OTHER,
    ) == Demotion.MIXED_CLAIM_NO_EXCEPTION


def test_simple_utterance_keeps_authentic_primary_exception():
    body = (
        "Versión taquigráfica. Diputada Myriam Bregman: es un vejestorio jurídico que no se aplica a menores. "
        "Fin de la transcripción del dicho en el recinto."
    )
    excerpt = "es un vejestorio jurídico que no se aplica a menores"
    row = _authentic_row(
        body=body,
        excerpt=excerpt,
        url="https://www.hcdn.gob.ar/transcript/bregman",
        domain="hcdn.gob.ar",
    )
    row.source_item.source.is_monitored = False
    claim = _origin_claim(
        text=SIMPLE_UTTERANCE,
        claim_type="declaracion",
        subject="Bregman",
        predicate="dijo",
        evidence=[row],
    )
    assert is_mixed_proposition(SIMPLE_UTTERANCE, "declaracion") is False
    assert proposition_role_for(claim) == PropositionRole.UTTERANCE
    assert classify_statement_row(claim, row) == StatementEvidenceClass.AUTHENTIC_PRIMARY
    assert assess_origins(claim).statement_evidence_class == StatementEvidenceClass.AUTHENTIC_PRIMARY
    assert clamp_supported_status(claim, ClaimStatus.SUPPORTED) == ClaimStatus.SUPPORTED


def test_split_does_not_copy_supports_status_or_basis_to_reaction():
    parts = split_compound_extracted(_raw(ACT_REACTION, excerpt=PUBLICATION_EXCERPT))
    publication = next(part for part in parts if part.predicate != "reaccion")
    reaction = next(part for part in parts if part.predicate == "reaccion")
    pub_body = (
        f"{PUBLICATION_EXCERPT}. La captura reproduce el texto original de la publicación "
        "en la cuenta verificada sin mediación de otro medio."
    )
    pub_row = _authentic_row(body=pub_body, excerpt=PUBLICATION_EXCERPT)
    react_row = SimpleNamespace(
        evidence_type=reaction.evidence[0].evidence_type,
        excerpt=reaction.evidence[0].excerpt,
        source_item=pub_row.source_item,
        source_url=pub_row.source_url,
    )
    pub_claim = _origin_claim(
        text=publication.canonical_text,
        claim_type=publication.claim_type,
        subject="Milei",
        predicate=publication.predicate,
        evidence=[pub_row],
    )
    react_claim = _origin_claim(
        text=reaction.canonical_text,
        claim_type="hecho",
        subject="Milei",
        predicate="reaccion",
        evidence=[react_row],
    )
    assert assess_origins(pub_claim).statement_evidence_class == StatementEvidenceClass.AUTHENTIC_PRIMARY
    assert clamp_supported_status(pub_claim, ClaimStatus.SUPPORTED) == ClaimStatus.SUPPORTED
    assert react_row.evidence_type != EvidenceType.SUPPORTS
    react_assessment = assess_origins(react_claim)
    assert react_assessment.statement_evidence_class != StatementEvidenceClass.AUTHENTIC_PRIMARY
    react_status = apply_primary_requirement(
        react_claim, ClaimStatus.SUPPORTED, heuristic_plan(react_claim), primary_supports=False
    )
    assert react_status != ClaimStatus.SUPPORTED
    assert clamp_supported_status(react_claim, ClaimStatus.SUPPORTED) != ClaimStatus.SUPPORTED


def test_reaction_with_ordinary_support_is_not_degraded_for_being_split():
    parts = split_compound_extracted(
        _raw(
            ACT_REACTION,
            excerpt=REACTION_EXCERPT,
            evidence=[
                ExtractedEvidence(source_ref=1, evidence_type=EvidenceType.SUPPORTS, excerpt=PUBLICATION_EXCERPT),
                ExtractedEvidence(source_ref=1, evidence_type=EvidenceType.SUPPORTS, excerpt=REACTION_EXCERPT),
            ],
        )
    )
    reaction = next(part for part in parts if part.predicate == "reaccion")
    assert any(ev.evidence_type == EvidenceType.SUPPORTS and ev.excerpt == REACTION_EXCERPT for ev in reaction.evidence)
    body_a = (
        "El anuncio generó polémica en el Congreso durante la sesión especial "
        "y diputados de la oposición cruzaron acusaciones sobre el recorte."
    )
    body_b = (
        "En redes y sindicatos la medida despertó una ola de críticas distintas "
        "a las de la sesión: el mensaje publicado el lunes generó polémica inmediata."
    )
    row_a = _row(
        url="https://medio-a.test/n",
        excerpt="El anuncio generó polémica en el Congreso durante la sesión especial",
        body=body_a,
        domain="medio-a.test",
    )
    row_b = _row(
        url="https://medio-b.test/n",
        excerpt="el mensaje publicado el lunes generó polémica inmediata",
        body=body_b,
        domain="medio-b.test",
    )
    claim = _origin_claim(
        text=reaction.canonical_text,
        claim_type="hecho",
        importance=ClaimImportance.HIGH,
        subject="Milei",
        predicate="reaccion",
        evidence=[row_a, row_b],
    )
    assessment = assess_origins(claim)
    assert assessment.known_independent >= 2
    status = apply_primary_requirement(claim, ClaimStatus.SUPPORTED, heuristic_plan(claim), primary_supports=False)
    assert status == ClaimStatus.SUPPORTED
    assert clamp_supported_status(claim, ClaimStatus.SUPPORTED) == ClaimStatus.SUPPORTED


def test_negation_modality_figures_and_time_survive_split():
    parts = split_compound_extracted(
        _raw(
            NEGATED,
            excerpt=NEGATED,
            subject="Milei",
            normalized_value="3",
            unit="mensajes",
        )
    )
    assert len(parts) == 2
    publication = next(part for part in parts if part.predicate != "reaccion")
    reaction = next(part for part in parts if part.predicate == "reaccion")
    assert "no publicó" in publication.canonical_text.lower() or "no publico" in publication.canonical_text.lower()
    assert "ayer" in publication.canonical_text.lower()
    assert "no generó polémica" in reaction.canonical_text.lower() or "no genero polemica" in reaction.canonical_text.lower()
    modal_parts = split_compound_extracted(
        _raw(MODAL_FIGURE, excerpt=MODAL_FIGURE, subject="Milei", normalized_value="3", unit="mensajes")
    )
    publication = next(part for part in modal_parts if part.predicate != "reaccion")
    reaction = next(part for part in modal_parts if part.predicate == "reaccion")
    assert "habría publicado" in publication.canonical_text.lower() or "habria publicado" in publication.canonical_text.lower()
    assert "3 mensajes" in publication.canonical_text
    assert "2 de marzo" in publication.canonical_text.lower()
    assert reaction.normalized_value is None
    assert "3" not in (reaction.canonical_text or "")


def test_existing_bregman_and_judge_splits_remain():
    bregman = split_compound_extracted(_raw(BREGMAN, excerpt="entra en vigencia", subject="Bregman"))
    assert len(bregman) >= 2
    assert any(part.predicate == "dijo" for part in bregman)
    assert any(part.predicate in {"vigencia", "alcance"} for part in bregman)
    judge = split_compound_extracted(
        _raw(
            "La jueza María Servini suspendió la Ley 27.801 y dijo: «Esta norma es inconstitucional»",
            excerpt="suspendió la Ley",
            claim_type="hecho",
            subject="Servini",
        )
    )
    assert any(part.predicate == "dijo" for part in judge)
    assert any(part.predicate == "resolucion" for part in judge)


def test_coverage_before_after_keeps_material_core(db_session: Session) -> None:
    source = _source(db_session)
    title = "Milei publicó un mensaje y generó polémica"
    body = f"{title}. {PUBLICATION_EXCERPT}. {REACTION_EXCERPT}."
    item = _item(db_session, source.id, url="https://medio.test/c8", title=title, body=body, content_hash="c8cov")
    event = _event(db_session, item, title_internal=title, short_summary=title)
    before = expected_centrals_from_event(event)
    before_split = is_mixed_proposition(title)
    llm = FakeStructuredLLM(
        {
            "ClaimExtractionBatch": ClaimExtractionBatch(
                claims=[
                    _extracted(
                        text=title,
                        claim_type="declaracion",
                        excerpt=PUBLICATION_EXCERPT,
                        subject="Milei",
                        predicate="publico",
                    )
                ]
            ),
            "ClaimResolutionBatch": _resolution("acto", "reaccion"),
        }
    )
    result = ClaimService(db_session, extractor_llm=llm, resolver_llm=llm).resolve(event.id, trigger="admin")
    claims = list(db_session.scalars(select(Claim).where(Claim.event_id == event.id)))
    texts = [claim.canonical_text.lower() for claim in claims]
    coverage = result["coverage"]
    expected = coverage["expected_central"]
    assert before_split is True
    assert any("public" in text for text in texts)
    assert any(row.get("act") == "utterance" for row in expected)
    assert all("hubo polémica" not in (row.get("proposition") or "").lower() for row in expected)
    assert all(row.get("role") != PropositionRole.UTTERANCE.value or "generó polémica" not in (row.get("proposition") or "").lower() for row in expected)
    pub_expected = [row for row in expected if row.get("act") == "utterance"]
    assert pub_expected
    assert any(row.get("match") == CoverageMatch.EQUIVALENT.value for row in pub_expected)
    reaction_central = [
        row
        for row in expected
        if "generó polémica" in (row.get("proposition") or "").lower() and row.get("act") != "utterance"
    ]
    assert not reaction_central
    assert before
    _ = before


def test_idempotent_extract_and_incremental_do_not_duplicate(db_session: Session) -> None:
    source = _source(db_session)
    title = ACT_REACTION
    body = f"{title}. {PUBLICATION_EXCERPT}."
    item = _item(db_session, source.id, url="https://medio.test/c8id", title=title, body=body, content_hash="c8id")
    event = _event(db_session, item, title_internal=title)
    batch = ClaimExtractionBatch(
        claims=[
            _extracted(
                text=title,
                claim_type="declaracion",
                excerpt=PUBLICATION_EXCERPT,
                subject="Milei",
                predicate="publico",
            )
        ]
    )
    llm = FakeStructuredLLM(
        {"ClaimExtractionBatch": batch, "ClaimResolutionBatch": _resolution("acto", "reaccion")}
    )
    service = ClaimService(db_session, extractor_llm=llm, resolver_llm=llm)
    first = service.resolve(event.id, trigger="admin")
    second = service.resolve(event.id, trigger="admin")
    claims = list(db_session.scalars(select(Claim).where(Claim.event_id == event.id)))
    evidence_rows = list(db_session.scalars(select(ClaimEvidence).where(ClaimEvidence.claim_id.in_([c.id for c in claims]))))
    assert first["persisted"] == second["persisted"] == len(claims)
    assert len(claims) == 2
    assert len(evidence_rows) == len({(row.claim_id, row.source_item_id) for row in evidence_rows})
    other = _source(db_session, name="Otra", domain="otra.test", feed_url="https://otra.test/rss.xml")
    item_b = _item(
        db_session,
        other.id,
        url="https://otra.test/c8id",
        title=title,
        body=body,
        content_hash="c8idb",
    )
    EventService(db_session).attach_source(event, item_b.id, relation_type=EventSourceRelation.ADDITIONAL)
    incremental_llm = FakeStructuredLLM(
        {"ClaimExtractionBatch": batch, "ClaimResolutionBatch": _resolution("acto", "reaccion")}
    )
    incremental = ClaimService(db_session, extractor_llm=incremental_llm, resolver_llm=incremental_llm).resolve(
        event.id, trigger="admin", source_item_id=item_b.id
    )
    after = list(db_session.scalars(select(Claim).where(Claim.event_id == event.id)))
    assert len(after) == 2
    assert incremental.get("incremental") is True
    origins = []
    for claim in after:
        db_session.refresh(claim)
        origins.append(len(assess_origins(claim).information_origins))
    assert max(origins) <= 2


def test_reused_document_is_not_several_independent_origins():
    parts = split_compound_extracted(_raw(ACT_REACTION, excerpt=PUBLICATION_EXCERPT))
    row = _authentic_row(body=f"{PUBLICATION_EXCERPT}. {ACT_REACTION}", excerpt=PUBLICATION_EXCERPT)
    for part in parts:
        claim = _origin_claim(
            text=part.canonical_text,
            claim_type=part.claim_type,
            subject="Milei",
            predicate=part.predicate,
            evidence=[
                SimpleNamespace(
                    evidence_type=part.evidence[0].evidence_type,
                    excerpt=part.evidence[0].excerpt,
                    source_item=row.source_item,
                    source_url=row.source_url,
                )
            ],
        )
        assessment = assess_origins(claim)
        assert assessment.known_independent <= 1
        assert len({item.split(":")[0] for item in assessment.information_origins}) <= 1


def test_c1_c3_c6_follow_the_component(db_session: Session) -> None:
    source = _source(db_session, is_monitored=False, domain="x.com")
    title = ACT_REACTION
    body = f"{PUBLICATION_EXCERPT}. {title}."
    item = _item(db_session, source.id, url="https://x.com/status/c8", title=title, body=body, content_hash="c8c1")
    event = _event(db_session, item, title_internal=title)
    llm = FakeStructuredLLM(
        {
            "ClaimExtractionBatch": ClaimExtractionBatch(
                claims=[
                    _extracted(
                        text=title,
                        claim_type="declaracion",
                        excerpt=PUBLICATION_EXCERPT,
                        subject="Milei",
                        predicate="publico",
                    )
                ]
            ),
            "ClaimResolutionBatch": _resolution("acto", "reaccion"),
        }
    )
    extract = ClaimService(db_session, extractor_llm=llm, resolver_llm=llm).resolve(event.id, trigger="admin")
    assert "CheapClaimEvidenceAssessment" not in llm.calls
    claims = list(db_session.scalars(select(Claim).where(Claim.event_id == event.id)))
    assert len(claims) == 2
    publication = next(claim for claim in claims if "public" in claim.canonical_text.lower())
    reaction = next(claim for claim in claims if claim.predicate == "reaccion" or "polémica" in claim.canonical_text.lower())
    pub_types = {row.evidence_type for row in publication.evidence}
    assert EvidenceType.SUPPORTS in pub_types
    assert proposition_role_for(reaction) != PropositionRole.UTTERANCE
    assert assess_origins(reaction).statement_evidence_class != StatementEvidenceClass.AUTHENTIC_PRIMARY
    assert clamp_supported_status(reaction, ClaimStatus.SUPPORTED) != ClaimStatus.SUPPORTED
    verify_llm = FakeStructuredLLM({"VerificationResult": _sol()})
    service = _verify_service(db_session, verify_llm, FakeSearchProvider())
    service.settings = service.settings.model_copy(update={"max_verification_claims_per_event": 1})
    verified = service.verify(event.id, trigger="admin")
    assert get_settings().max_verification_claims_per_event == 5
    decisions = verified["decision_by_claim_id"]
    states = {row["evaluation_state"] for row in decisions.values()}
    assert "complete" in states
    assert "skipped" in states
    skipped = next(row for row in decisions.values() if row["evaluation_state"] == "skipped")
    assert skipped.get("llm_reason") in {"budget", "policy_skip", "veto"}
    complete = next(row for row in decisions.values() if row["evaluation_state"] == "complete")
    assert complete.get("reason_code")
    assert complete.get("verified_scope") in {None, publication.canonical_text, reaction.canonical_text}
    assert "evaluation_state" not in ContextClaimDecision.model_fields
    assert extract["extracted"] == 1
    assert len(claims) > extract["extracted"]


def test_c7_split_utterance_and_content_are_not_conflicting():
    raw = ExtractedClaim(
        canonical_text="Milei afirmó que su Gobierno eliminó unas 17.000 normas y generó polémica",
        claim_type="declaracion",
        subject="Milei",
        evidence=[ExtractedEvidence(source_ref=1, evidence_type=EvidenceType.SUPPORTS, excerpt="afirmó que su Gobierno eliminó unas 17.000 normas")],
        factual_content=ExtractedProposition(
            canonical_text="El Gobierno de Milei eliminó unas 17.000 normas",
            claim_type="cifra",
            subject="Gobierno de Milei",
            predicate="eliminó",
            object_text="unas 17.000 normas",
            normalized_value="17000",
            unit="normas",
        ),
    )
    layers = split_attributed_content(raw)
    parts: list[ExtractedClaim] = []
    for layer in layers:
        parts.extend(split_compound_extracted(layer))
    utterance = next(part for part in parts if part.claim_type == "declaracion" and "generó polémica" not in (part.canonical_text or ""))
    factual = next(part for part in parts if part.claim_type == "cifra")
    reaction = next(part for part in parts if part.predicate == "reaccion")
    assert comparison_key_for(utterance) != comparison_key_for(factual)
    comparable, reason = conflict_comparability(utterance, factual)
    assert comparable is False
    assert reason == "utterance_versus_content"
    comparable_reaction, _ = conflict_comparability(utterance, reaction)
    assert comparable_reaction is False


def test_c2_new_extraction_does_not_change_frozen_v1(db_session: Session) -> None:
    source = _source(db_session)
    title = "Milei habló en redes"
    body = "Milei publicó un mensaje."
    item = _item(db_session, source.id, url="https://medio.test/c8v1", title=title, body=body, content_hash="c8v1")
    event = _event(db_session, item, title_internal=title)
    claim = _db_claim(
        db_session,
        event,
        text="Milei publicó un mensaje",
        claim_type="declaracion",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.SINGLE_SOURCE,
        subject="Milei",
        predicate="publico",
    )
    _db_evidence(db_session, claim, item, excerpt="Milei publicó un mensaje")
    article, _created = ArticleService(db_session).create_draft(
        ArticleCreate(
            event_id=event.id,
            headline="Según la cuenta, Milei publicó un mensaje",
            summary="Según la cuenta, Milei publicó un mensaje.",
            body="Según la cuenta, Milei publicó un mensaje.",
            body_blocks=[
                {
                    "type": "paragraph",
                    "segments": [{"text": "Según la cuenta, Milei publicó un mensaje.", "claim_ids": [str(claim.id)]}],
                }
            ],
        )
    )
    persist_version_snapshot(db_session, event, article)
    first, _audit_llm = _audit(db_session, event, result=_pass_audit())
    assert first["passed"] is True
    published = PublishService(db_session).publish(event.id, trigger="test")
    assert published["published"] is True
    db_session.refresh(article)
    db_session.commit()
    v1 = article.published_version
    frozen = compact_public_claims(db_session, event, freeze_to_version=v1)
    with TestClient(app) as client:
        before = client.get(f"/api/v1/articles/{article.slug}").json()
    assert before["published_version"] == v1
    assert [row["id"] for row in before["claims"]] == [row["id"] for row in frozen]
    assert [row["canonical_text"] for row in before["claims"]] == [row["canonical_text"] for row in frozen]
    llm = FakeStructuredLLM(
        {
            "ClaimExtractionBatch": ClaimExtractionBatch(
                claims=[
                    _extracted(
                        text=ACT_REACTION,
                        claim_type="declaracion",
                        excerpt=PUBLICATION_EXCERPT,
                        subject="Milei",
                        predicate="publico",
                    )
                ]
            ),
            "ClaimResolutionBatch": _resolution("acto", "reaccion"),
        }
    )
    ClaimService(db_session, extractor_llm=llm, resolver_llm=llm).resolve(event.id, trigger="admin")
    still = compact_public_claims(db_session, event, freeze_to_version=v1)
    assert still == frozen
    live = compact_public_claims(db_session, event)
    assert len(live) >= len(frozen)
    db_session.commit()
    with TestClient(app) as client:
        after = client.get(f"/api/v1/articles/{article.slug}").json()
    assert after["published_version"] == v1
    assert after["headline"] == before["headline"]
    assert after["claims"] == before["claims"]


def test_selection_cap_materiality_and_no_new_llm_round(db_session: Session) -> None:
    source = _source(db_session)
    title = ACT_REACTION
    body = f"{title}. {PUBLICATION_EXCERPT}."
    item = _item(db_session, source.id, url="https://medio.test/c8cap", title=title, body=body, content_hash="c8cap")
    event = _event(db_session, item, title_internal=title)
    llm = FakeStructuredLLM(
        {
            "ClaimExtractionBatch": ClaimExtractionBatch(
                claims=[
                    _extracted(
                        text=title,
                        claim_type="declaracion",
                        excerpt=PUBLICATION_EXCERPT,
                        subject="Milei",
                        predicate="publico",
                    )
                ]
            ),
            "ClaimResolutionBatch": _resolution("acto", "reaccion"),
        }
    )
    ClaimService(db_session, extractor_llm=llm, resolver_llm=llm).resolve(event.id, trigger="admin")
    assert llm.calls.count("ClaimExtractionBatch") == 1
    assert llm.calls.count("ClaimResolutionBatch") == 1
    assert "CheapClaimEvidenceAssessment" not in llm.calls
    claims = list(db_session.scalars(select(Claim).where(Claim.event_id == event.id)))
    selected, skipped = select_claims(claims, flagged_ids=set(), limit=1, central_ids={claim.id for claim in claims})
    assert len(selected) == 1
    assert any(row.get("reason") == "budget" for row in skipped)
    previous = snapshot_claims(
        [
            SimpleNamespace(
                id=uuid4(),
                canonical_text=ACT_REACTION,
                status=ClaimStatus.SINGLE_SOURCE,
                importance=ClaimImportance.HIGH,
                normalized_value=None,
                unit=None,
                claim_type="declaracion",
                subject="Milei",
                predicate="publico",
                object_text=ACT_REACTION,
            )
        ]
    )
    current = snapshot_claims(claims)
    change = detect_material_change(previous, current)
    assert "new_high_claim" in change.reasons
    assert change.is_material is True
    assert get_settings().max_verification_claims_per_event == 5
