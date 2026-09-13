"""Material attributed facts: existing services, fake providers, no live searches."""
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.domain.enums import ClaimImportance, ClaimStatus, EvidenceType
from app.schemas.claims import ClaimExtractionBatch, ClaimResolutionBatch, ExtractedClaim, ExtractedEvidence, ExtractedProposition
from app.services.claim_meaning import preserve_extracted_meaning, split_attributed_content
from app.services.verification_policy import select_claims
from tests.test_claims import _source, _item, _event, _llm, _service, _event_claims

STATEMENT = "Milei afirmó que su Gobierno eliminó unas 17.000 normas."
FACT = "El Gobierno de Milei eliminó unas 17.000 normas."


def extracted_pair():
    return ExtractedClaim(
        canonical_text=STATEMENT, claim_type="declaracion", subject="Milei",
        evidence=[ExtractedEvidence(source_ref=1, evidence_type=EvidenceType.SUPPORTS, excerpt=STATEMENT)],
        factual_content=ExtractedProposition(
            canonical_text=FACT, claim_type="cifra", subject="Gobierno de Milei", predicate="eliminó",
            object_text="unas 17.000 normas", normalized_value="17000", unit="normas",
        ),
    )


def test_extraction_persists_both_layers_and_reuses_ids(db_session):
    source = _source(db_session)
    item = _item(db_session, source.id, url="https://ejemplo.test/normas", title="Reformas",
                 body=STATEMENT, content_hash="normas")
    event = _event(db_session, item, title_internal="Reformas", short_summary=STATEMENT)
    results = []
    for _ in range(2):
        llm = _llm(ClaimExtractionBatch(claims=[extracted_pair()]), ClaimResolutionBatch())
        result = _service(db_session, llm).resolve(event.id, trigger="test")
        assert "error" not in result
        results.append(result["attribution_pairs"])
    claims = _event_claims(db_session, event.id)
    assert len(claims) == 2
    assert results[0] == results[1]
    statement = next(c for c in claims if c.claim_type == "declaracion")
    factual = next(c for c in claims if c.claim_type == "cifra")
    assert statement.canonical_text == STATEMENT and statement.normalized_value is None
    assert factual.canonical_text == FACT and factual.normalized_value == "17000"
    assert factual.unit == "normas" and factual.occurred_at is None
    assert all(c.status == ClaimStatus.SINGLE_SOURCE for c in claims)
    assert results[0] == [{"attribution_claim_id": str(statement.id), "factual_claim_id": str(factual.id)}]


@pytest.mark.parametrize("text", [
    "Milei afirmó que sus reformas son las más importantes de los últimos 100 años.",
    "Milei afirmó que su Gobierno hizo más reformas que todos los gobiernos de los últimos 100 años combinados.",
])
def test_opinion_does_not_get_a_numeric_derivation(text):
    raw = preserve_extracted_meaning(ExtractedClaim(canonical_text=text), [])
    layers = split_attributed_content(raw)
    assert len(layers) == 1 and layers[0].claim_type == "declaracion"
    assert layers[0].normalized_value is None


def test_paraphrases_dedupe_using_normalized_dimensions_and_keep_id(db_session):
    a = "Milei implementará un paquete de reformas más profundo."
    b = "Milei abrirá una nueva etapa con reformas aún más profundas."
    source = _source(db_session)
    item = _item(db_session, source.id, url="https://ejemplo.test/promesa", title="Reformas",
                 body=a + " " + b, content_hash="promesa")
    event = _event(db_session, item, title_internal="Reformas", short_summary=a)
    def raw(text):
        return ExtractedClaim(canonical_text=text, claim_type="declaracion", subject="Milei",
                              predicate="anunció", object_text="nuevas reformas más profundas",
                              evidence=[ExtractedEvidence(source_ref=1, evidence_type=EvidenceType.SUPPORTS, excerpt=text)])
    for texts in ([a], [a, b]):
        result = _service(db_session, _llm(ClaimExtractionBatch(claims=[raw(t) for t in texts]), ClaimResolutionBatch())).resolve(event.id, trigger="test")
        assert "error" not in result
        claims = _event_claims(db_session, event.id)
        assert len(claims) == 1
        if len(texts) == 1:
            original_id = claims[0].id
    assert claims[0].id == original_id


@pytest.mark.parametrize("kind,text,flagged,expected", [
    ("cifra", FACT, False, True),
    ("documento", "Se aprobó la ley", False, True),
    ("hecho", "Se realizó el encuentro", False, False),
    ("hecho", "Se realizó el encuentro", True, True),
    ("hecho", "La resolución dispuso el nombramiento", False, True),
])
def test_medium_selection_and_explicit_flag(kind, text, flagged, expected):
    claim = SimpleNamespace(id=uuid4(), canonical_text=text, claim_type=kind,
                            importance=ClaimImportance.MEDIUM, status=ClaimStatus.SINGLE_SOURCE, evidence=[])
    selected, _ = select_claims([claim], flagged_ids={claim.id} if flagged else set(), limit=5)
    assert bool(selected) == expected
    claim.status = ClaimStatus.OUTDATED
    assert not select_claims([claim], flagged_ids={claim.id}, limit=5)[0]


def test_regulatory_planner_uses_official_record_and_native_domains():
    from app.services.verification_plan import heuristic_plan, build_verification_searches
    from app.services.evidence_source_registry import preferred_domains
    from app.services.verification_service import VerificationService
    from app.providers.fakes import FakeStructuredLLM
    from tests.test_verification_plan import _claim
    claim = _claim(canonical_text=FACT)
    planner = FakeStructuredLLM()
    plan = VerificationService(None, planner_llm=planner)._plan_for(claim, None)
    assert not planner.calls
    assert plan.verification_target.value == "OFFICIAL_RECORD"
    assert plan.temporal_scope.value == "UNKNOWN_PERIOD"
    domains = preferred_domains(plan.jurisdiction, plan.verification_target.value, plan.subject.value)
    queries = build_verification_searches(claim, plan, domains, limit=3, count=3)
    assert len(queries) == 2
    assert set(queries[0].include_domains) == {"argentina.gob.ar", "boletinoficial.gob.ar"}
    assert queries[1].include_domains is None
    assert all("17.000" in q.text and "normas" in q.text and "site:" not in q.text for q in queries)
    assert all(q.since is None and q.until is None for q in queries)
    assert heuristic_plan(_claim(canonical_text="La inflación mensual fue 1,7%.")).verification_target.value == "OFFICIAL_STATISTICS"


def test_multiple_reports_do_not_establish_independence(db_session):
    from tests.test_verification import _claim, _evidence, _service as verification_service
    from app.providers.fakes import FakeStructuredLLM, FakeSearchProvider
    from app.schemas.verification import VerificationResult, VerificationEvidence
    from app.services.information_origin import assess_origins
    source = _source(db_session)
    item = _item(db_session, source.id, url="https://a.test/normas", title="Reformas", body=STATEMENT, content_hash="rep1")
    event = _event(db_session, item, title_internal="Reformas", short_summary=STATEMENT)
    claim = _claim(db_session, event, text=FACT, claim_type="cifra", importance=ClaimImportance.MEDIUM,
                   status=ClaimStatus.SINGLE_SOURCE, subject="Gobierno de Milei", normalized_value="17000", unit="normas")
    for index, doc in enumerate([item] + [
        _item(db_session, source.id, url=f"https://{host}.test/normas", title="Reformas", body=STATEMENT, content_hash=f"rep{host}")
        for host in ("b", "c")
    ], 1):
        _evidence(db_session, claim, doc, excerpt=STATEMENT)
    llm = FakeStructuredLLM({"VerificationResult": VerificationResult(
        status=ClaimStatus.SUPPORTED, evidence=[VerificationEvidence(source_ref=i, evidence_type=EvidenceType.SUPPORTS, excerpt=STATEMENT) for i in (1, 2, 3)]
    )})
    search = FakeSearchProvider()
    result = verification_service(db_session, llm, search).verify(event.id, trigger="test")
    assert "error" not in result
    decision = result["decision_by_claim_id"][str(claim.id)]
    basis = decision["support_basis"]
    assert claim.status == ClaimStatus.SINGLE_SOURCE
    assert basis["documents_supporting"] == 3
    assert basis["known_independent_count"] == 0 and basis["unknown_group_count"] > 0
    assert basis["primary_access"] == "not_found"
    assert len(result["search_requests"][str(claim.id)]) == 2
    assert len(search.queries) == 2


@pytest.mark.parametrize("variant,expected", [
    ("comparable", ClaimStatus.SUPPORTED),
    ("category_mismatch", ClaimStatus.SINGLE_SOURCE),
    ("other_period", ClaimStatus.SINGLE_SOURCE),
    ("missing_comparison", ClaimStatus.SINGLE_SOURCE),
    ("reported_statement", ClaimStatus.SINGLE_SOURCE),
])
def test_primary_count_requires_comparable_observation(db_session, variant, expected):
    from tests.test_verification import _claim, _evidence
    from app.schemas.evidence_comparison import EvidenceComparison, Measurement
    from app.schemas.verification import VerificationResult, VerificationEvidence
    from app.services.verification_plan import heuristic_plan
    from app.services.verification_service import VerificationService, _PacketSource
    text = "El Gobierno de Milei eliminó unas 17.000 normas en agosto de 2026."
    body = "El Gobierno de Milei eliminó 17.000 normas en agosto de 2026."
    if variant == "category_mismatch":
        body = "El Gobierno de Milei eliminó 2.800 normativas y 17.000 artículos en agosto de 2026."
    if variant == "other_period":
        body = body.replace("agosto", "julio")
    if variant == "reported_statement":
        body = STATEMENT
    source = _source(db_session)
    report = _item(db_session, source.id, url="https://a.test/normas", title="Reformas", body=STATEMENT, content_hash="rep")
    event = _event(db_session, report)
    claim = _claim(db_session, event, text=text, claim_type="cifra", importance=ClaimImportance.MEDIUM,
                   status=ClaimStatus.SINGLE_SOURCE, normalized_value="17000", unit="normas")
    _evidence(db_session, claim, report, excerpt=STATEMENT)
    official = _item(db_session, source.id, url="https://argentina.gob.ar/registro", title="Registro",
                     body=body, content_hash="primary")
    official.metadata_json = {"body_source": "extracted_html", "fetch_ok": True}
    left = Measurement(indicator="eliminó", unit="normas", scope="Gobierno de Milei", period="agosto de 2026", value="17000")
    right = left.model_copy(update={"unit": "artículos" if variant == "category_mismatch" else "normas",
                                    "period": "julio de 2026" if variant == "other_period" else "agosto de 2026"})
    comparison = EvidenceComparison(proposition="statistic", basis="same_value", claim_fragment=text,
                                    evidence_fragment=body, claim_measurement=left, evidence_measurement=right, reason="Registro comparable")
    result = VerificationResult(status=ClaimStatus.SUPPORTED, evidence=[VerificationEvidence(
        source_ref=1, evidence_type=EvidenceType.SUPPORTS, excerpt=body,
        comparison=None if variant == "missing_comparison" else comparison)])
    packet = [_PacketSource(ref=1, url=official.url, title="Registro", snippet=body, item=official, body_source="extracted_html")]
    *_, decision = VerificationService(db_session)._apply_result(event, claim, packet, result, heuristic_plan(claim), ["argentina.gob.ar"], False)
    assert claim.status == expected
    assert decision.support_basis.primary_access == ("found_relevant" if variant == "comparable" else "found_unrelated")
    if variant not in {"comparable", "reported_statement"}:
        assert decision.support_basis.documents_qualifying == 1
