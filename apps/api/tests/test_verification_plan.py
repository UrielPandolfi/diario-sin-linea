from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from app.core.prompts import load_prompt
from app.domain.enums import ClaimImportance, ClaimStatus, EvidenceType
from app.schemas.verification import (
    CheapClaimEvidenceAssessment,
    CheapEvidenceJudgement,
    EvidenceJudgementType,
    TemporalScope,
    VerificationPlan,
    VerificationSubject,
    VerificationTarget,
)
from app.services.evidence_source_registry import preferred_domains
from app.services.verification_plan import (
    build_verification_queries,
    freshness_for_plan,
    heuristic_plan,
    needs_sol_after_assessment,
    refine_plan,
    skip_directed_search,
    year_hint_from_claim,
)
from app.services.verification_policy import policy_selects, select_claims


def _claim(**overrides):
    payload = {
        "id": uuid4(),
        "canonical_text": "El IPC de julio fue 2,1%",
        "claim_type": "cifra",
        "importance": ClaimImportance.HIGH,
        "status": ClaimStatus.SINGLE_SOURCE,
        "occurred_at": None,
        "subject": None,
        "predicate": None,
        "object_text": None,
        "normalized_value": None,
        "unit": None,
        "evidence": [],
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def test_prompt_requires_atomic_material_claims() -> None:
    prompt = load_prompt("claim_extraction.md")
    assert "una proposición material" in prompt
    assert "profundas críticas" in prompt
    assert "Y cometió delito Z" in prompt
    assert "estimación, proyección o dato oficial" in prompt


def test_extraction_keeps_accusation_discards_vague_and_splits_compound() -> None:
    prompt = load_prompt("claim_extraction.md")
    folded = prompt.casefold()
    assert "tuvo acceso total a información estratégica" in prompt
    assert "cargo de alta sensibilidad" in prompt
    assert "sectores afines" in prompt
    assert "separalas" in folded
    assert "decisión judicial" in folded
    assert "detalles probatorios secundarios" in folded
    assert "comparación se resuelve después por código" in folded


def test_writing_and_audit_block_unattributed_single_source() -> None:
    writing = load_prompt("article_writing.md")
    audit = load_prompt("article_audit.md")
    assert "NUNCA se convierte en hecho afirmado por Sin Línea" in writing
    assert "Según [fuente], en 2009 fue nombrada subsecretaria" in writing
    assert "Si el draft lo afirma como hecho de Sin Línea, reportá ATTRIBUTION" in audit


def test_denuncia_is_not_guilt_in_resolution_and_assessment_prompts() -> None:
    resolution = load_prompt("claim_resolution.md")
    assess = load_prompt("claim_evidence_assessment.md")
    writing = load_prompt("article_writing.md")
    assert "veracidad de lo denunciado" in resolution
    assert "denuncia no establece que lo denunciado sea verdadero" in assess
    assert "no autoriza" in writing


def test_projection_is_not_official_statistic_in_prompts() -> None:
    plan = load_prompt("verification_plan.md")
    assess = load_prompt("claim_evidence_assessment.md")
    writing = load_prompt("article_writing.md")
    assert "Estimación o proyección privada" in plan
    assert "estimación privada no establece un dato oficial" in assess
    assert "estimación, proyección o expectativa privada" in writing


def test_registry_prioritizes_indec_boletin_and_mendoza_courts() -> None:
    stats = preferred_domains("AR", "OFFICIAL_STATISTICS", "STATISTICS")
    assert stats[0] == "indec.gob.ar"
    appointments = preferred_domains("AR", "OFFICIAL_RECORD", "GOVERNMENT_APPOINTMENT")
    assert "boletinoficial.gob.ar" in appointments
    judicial = preferred_domains("AR", "JUDICIAL_RECORD", "JUDICIAL_CASE", province="Mendoza")
    assert judicial[0] == "jus.mendoza.gov.ar"
    assert "csjn.gov.ar" in judicial


def test_registry_includes_regulated_tariff_domains() -> None:
    domains = preferred_domains("AR", "OFFICIAL_RECORD", "REGULATED_TARIFF")
    assert "energia.gob.ar" in domains
    assert "enre.gob.ar" in domains
    assert "enargas.gob.ar" in domains
    assert "eras.gob.ar" in domains
    assert "aysa.com.ar" in domains
    assert "indec.gob.ar" not in domains


def test_heuristic_plan_maps_types_and_historical_year() -> None:
    cifra = _claim(claim_type="cifra", canonical_text="El IPC de julio fue 2,1%")
    plan = heuristic_plan(cifra)
    assert plan.verification_target == VerificationTarget.OFFICIAL_STATISTICS
    assert plan.subject == VerificationSubject.STATISTICS
    assert plan.primary_source_required is True

    tariff = _claim(claim_type="cifra", canonical_text="Las facturas de electricidad aumentarán 1,75%")
    tariff_plan = heuristic_plan(tariff)
    assert tariff_plan.verification_target == VerificationTarget.OFFICIAL_RECORD
    assert tariff_plan.subject == VerificationSubject.REGULATED_TARIFF

    aysa = _claim(claim_type="cifra", canonical_text="AySA aumentará 0,8% en agosto")
    aysa_plan = heuristic_plan(aysa)
    assert aysa_plan.verification_target == VerificationTarget.OFFICIAL_RECORD
    assert aysa_plan.subject == VerificationSubject.REGULATED_TARIFF

    denuncia = _claim(
        claim_type="hecho",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.SINGLE_SOURCE,
        canonical_text="Víctor Eduardo Vital presentó una denuncia penal contra Natalia Laura Federman",
    )
    denuncia_plan = heuristic_plan(denuncia)
    assert denuncia_plan.verification_target == VerificationTarget.JUDICIAL_RECORD
    assert denuncia_plan.subject == VerificationSubject.JUDICIAL_CASE
    assert denuncia_plan.primary_source_required is True

    ruling = _claim(
        claim_type="hecho",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.SINGLE_SOURCE,
        canonical_text="La Corte desestimó el recurso de casación y confirmó el sobreseimiento",
    )
    ruling_plan = heuristic_plan(ruling)
    assert ruling_plan.verification_target == VerificationTarget.JUDICIAL_RECORD
    assert ruling_plan.subject == VerificationSubject.JUDICIAL_CASE

    documento = _claim(
        claim_type="documento",
        canonical_text="Natalia Laura Federman fue designada en 2011",
        occurred_at=datetime(2011, 6, 9, tzinfo=timezone.utc),
    )
    planned = heuristic_plan(documento)
    assert planned.verification_target == VerificationTarget.OFFICIAL_RECORD
    assert planned.temporal_scope == TemporalScope.HISTORICAL
    assert planned.year_hint == 2011
    assert freshness_for_plan(planned) is None


def test_historical_freshness_is_not_pd() -> None:
    plan = VerificationPlan(
        verification_target=VerificationTarget.OFFICIAL_RECORD,
        temporal_scope=TemporalScope.HISTORICAL,
        subject=VerificationSubject.GOVERNMENT_APPOINTMENT,
        year_hint=2011,
    )
    assert freshness_for_plan(plan) is None
    current = VerificationPlan(temporal_scope=TemporalScope.CURRENT)
    assert freshness_for_plan(current) == "pd"


def test_year_hint_from_canonical_text() -> None:
    claim = _claim(canonical_text="La designación se formalizó en 2011", occurred_at=None)
    assert year_hint_from_claim(claim) == 2011


def test_queries_include_site_and_general_fallback() -> None:
    claim = _claim(
        canonical_text="Natalia Laura Federman fue designada Directora Nacional de Derechos Humanos",
        claim_type="documento",
    )
    plan = VerificationPlan(
        verification_target=VerificationTarget.OFFICIAL_RECORD,
        temporal_scope=TemporalScope.HISTORICAL,
        subject=VerificationSubject.GOVERNMENT_APPOINTMENT,
        year_hint=2011,
        search_terms=["Natalia Laura Federman", "designación"],
        primary_source_required=True,
    )
    domains = preferred_domains("AR", plan.verification_target.value, plan.subject.value)
    queries = build_verification_queries(claim, plan, domains, limit=3)
    assert any("site:boletinoficial.gob.ar" in query for query in queries)
    assert any("site:" not in query for query in queries)
    assert len(queries) <= 3


def test_policy_skips_well_supported_declaration_not_high_stat() -> None:
    declaration = _claim(
        claim_type="declaracion",
        importance=ClaimImportance.MEDIUM,
        status=ClaimStatus.SUPPORTED,
        evidence=[
            SimpleNamespace(
                evidence_type=EvidenceType.SUPPORTS, source_item=None, source_url="https://a.test/n"
            ),
            SimpleNamespace(
                evidence_type=EvidenceType.SUPPORTS, source_item=None, source_url="https://b.test/n"
            ),
        ],
    )
    assert policy_selects(declaration) is False
    cifra = _claim(
        claim_type="cifra",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.SUPPORTED,
        evidence=declaration.evidence,
    )
    assert policy_selects(cifra) is True
    accusation = _claim(
        claim_type="hecho",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.SINGLE_SOURCE,
        canonical_text="Tuvo acceso total a información estratégica",
    )
    assert policy_selects(accusation) is True
    well_hecho = _claim(
        claim_type="hecho",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.SUPPORTED,
        evidence=declaration.evidence,
    )
    assert policy_selects(well_hecho) is False


def test_select_claims_still_vetoes_mundane() -> None:
    selected, skipped = select_claims(
        [
            _claim(
                claim_type="hecho",
                importance=ClaimImportance.LOW,
                status=ClaimStatus.SINGLE_SOURCE,
            )
        ],
        flagged_ids=set(),
        limit=5,
    )
    assert selected == []
    assert skipped[0]["reason"] == "veto"


def test_skip_search_for_well_supported_without_primary_need() -> None:
    claim = _claim(
        claim_type="declaracion",
        status=ClaimStatus.SUPPORTED,
        evidence=[
            SimpleNamespace(
                evidence_type=EvidenceType.SUPPORTS, source_item=None, source_url="https://a.test/n"
            ),
            SimpleNamespace(
                evidence_type=EvidenceType.SUPPORTS, source_item=None, source_url="https://b.test/n"
            ),
        ],
    )
    plan = VerificationPlan(
        verification_target=VerificationTarget.PRIMARY_STATEMENT,
        subject=VerificationSubject.PUBLIC_STATEMENT,
        primary_source_required=False,
    )
    assert skip_directed_search(claim, plan, []) is True


def test_official_domain_without_semantic_support_still_needs_sol() -> None:
    claim = _claim(claim_type="documento", status=ClaimStatus.SINGLE_SOURCE)
    plan = VerificationPlan(
        verification_target=VerificationTarget.OFFICIAL_RECORD,
        subject=VerificationSubject.GOVERNMENT_APPOINTMENT,
        primary_source_required=True,
    )
    assessment = CheapClaimEvidenceAssessment(
        judgements=[
            CheapEvidenceJudgement(
                source_ref=1,
                relation=EvidenceJudgementType.DOES_NOT_ESTABLISH,
                excerpt=None,
                reason="solo menciona el apellido",
            )
        ],
        ambiguous=False,
        reason="no establece la designación",
    )
    assert needs_sol_after_assessment(claim, plan, assessment, primary_support=False) is True


def test_cheap_support_without_ambiguity_skips_sol() -> None:
    claim = _claim(
        claim_type="documento",
        status=ClaimStatus.SINGLE_SOURCE,
        evidence=[
            SimpleNamespace(
                evidence_type=EvidenceType.SUPPORTS,
                source_item=None,
                source_url="https://medio.test/n",
            ),
            SimpleNamespace(
                evidence_type=EvidenceType.SUPPORTS,
                source_item=None,
                source_url="https://boletinoficial.gob.ar/d",
            ),
        ],
    )
    plan = VerificationPlan(
        verification_target=VerificationTarget.OFFICIAL_RECORD,
        subject=VerificationSubject.GOVERNMENT_APPOINTMENT,
        primary_source_required=True,
    )
    assessment = CheapClaimEvidenceAssessment(
        judgements=[
            CheapEvidenceJudgement(
                source_ref=1,
                relation=EvidenceJudgementType.SUPPORTS,
                excerpt="dase por designada",
                reason="el decreto nombra el cargo",
            )
        ],
        ambiguous=False,
    )
    assert needs_sol_after_assessment(claim, plan, assessment, primary_support=True) is False


def test_refine_plan_does_not_copy_event_recency_onto_historical_claim() -> None:
    fallback = VerificationPlan(
        verification_target=VerificationTarget.OFFICIAL_RECORD,
        temporal_scope=TemporalScope.HISTORICAL,
        subject=VerificationSubject.GOVERNMENT_APPOINTMENT,
        year_hint=2011,
        primary_source_required=True,
    )
    planned = VerificationPlan(
        verification_target=VerificationTarget.OFFICIAL_RECORD,
        temporal_scope=TemporalScope.CURRENT,
        subject=VerificationSubject.GOVERNMENT_APPOINTMENT,
        year_hint=None,
        search_terms=["Federman"],
    )
    refined = refine_plan(planned, fallback)
    assert refined.temporal_scope == TemporalScope.HISTORICAL
    assert refined.year_hint == 2011
    assert refined.search_terms == ["Federman"]


def test_refine_plan_reroutes_tariff_stats_and_court_records() -> None:
    fallback_tariff = VerificationPlan(
        verification_target=VerificationTarget.OFFICIAL_RECORD,
        subject=VerificationSubject.REGULATED_TARIFF,
        temporal_scope=TemporalScope.RECENT,
        primary_source_required=True,
    )
    planned_tariff = VerificationPlan(
        verification_target=VerificationTarget.OFFICIAL_STATISTICS,
        subject=VerificationSubject.STATISTICS,
        temporal_scope=TemporalScope.RECENT,
        search_terms=["1,75%"],
    )
    refined_tariff = refine_plan(planned_tariff, fallback_tariff)
    assert refined_tariff.verification_target == VerificationTarget.OFFICIAL_RECORD
    assert refined_tariff.subject == VerificationSubject.REGULATED_TARIFF
    assert refined_tariff.search_terms == ["1,75%"]

    fallback_court = VerificationPlan(
        verification_target=VerificationTarget.JUDICIAL_RECORD,
        subject=VerificationSubject.JUDICIAL_CASE,
        temporal_scope=TemporalScope.CURRENT,
        primary_source_required=True,
    )
    planned_court = VerificationPlan(
        verification_target=VerificationTarget.OFFICIAL_RECORD,
        subject=VerificationSubject.ACCUSATION,
        temporal_scope=TemporalScope.CURRENT,
    )
    refined_court = refine_plan(planned_court, fallback_court)
    assert refined_court.verification_target == VerificationTarget.JUDICIAL_RECORD
    assert refined_court.subject == VerificationSubject.JUDICIAL_CASE

    planned_accusation = VerificationPlan(
        verification_target=VerificationTarget.JUDICIAL_RECORD,
        subject=VerificationSubject.ACCUSATION,
        temporal_scope=TemporalScope.HISTORICAL,
        year_hint=2012,
    )
    refined_accusation = refine_plan(planned_accusation, fallback_court)
    assert refined_accusation.verification_target == VerificationTarget.JUDICIAL_RECORD
    assert refined_accusation.subject == VerificationSubject.JUDICIAL_CASE


def test_refine_plan_makes_undated_claim_timeless() -> None:
    fallback = VerificationPlan(temporal_scope=TemporalScope.TIMELESS, year_hint=None)
    planned = VerificationPlan(temporal_scope=TemporalScope.RECENT, year_hint=None)
    refined = refine_plan(planned, fallback)
    assert refined.temporal_scope == TemporalScope.TIMELESS


def test_current_year_hint_cannot_stay_historical() -> None:
    from app.services.verification_plan import normalize_temporal_scope

    now = datetime(2026, 9, 6, tzinfo=timezone.utc)
    planned = VerificationPlan(
        verification_target=VerificationTarget.JUDICIAL_RECORD,
        temporal_scope=TemporalScope.HISTORICAL,
        subject=VerificationSubject.JUDICIAL_CASE,
        year_hint=2026,
    )
    fallback = VerificationPlan(
        verification_target=VerificationTarget.JUDICIAL_RECORD,
        temporal_scope=TemporalScope.TIMELESS,
        subject=VerificationSubject.JUDICIAL_CASE,
        year_hint=2026,
    )
    refined = refine_plan(planned, fallback, now=now)
    assert refined.temporal_scope == TemporalScope.RECENT
    assert refined.year_hint == 2026
    normalized = normalize_temporal_scope(
        VerificationPlan(temporal_scope=TemporalScope.HISTORICAL, year_hint=2026),
        now=now,
    )
    assert normalized.temporal_scope == TemporalScope.RECENT


def test_numeric_comparison_uses_supported_siblings() -> None:
    from app.services.verification_plan import try_resolve_numeric_comparison

    comparison = _claim(
        claim_type="hecho",
        canonical_text="El incremento de electricidad y gas será por debajo del 2,1% que informó INDEC",
    )
    electricity = _claim(
        id=uuid4(),
        claim_type="cifra",
        status=ClaimStatus.SUPPORTED,
        canonical_text="La electricidad aumentará 1,75%",
        normalized_value="1.75",
    )
    gas = _claim(
        id=uuid4(),
        claim_type="cifra",
        status=ClaimStatus.SUPPORTED,
        canonical_text="El gas aumentará 1,40%",
        normalized_value="1.40",
    )
    assert try_resolve_numeric_comparison(comparison, [comparison, electricity, gas]) == ClaimStatus.SUPPORTED
    electricity.status = ClaimStatus.SINGLE_SOURCE
    gas.status = ClaimStatus.SINGLE_SOURCE
    assert try_resolve_numeric_comparison(comparison, [comparison, electricity, gas]) is None


def test_primary_required_blocks_supported_without_primary() -> None:
    from app.services.verification_plan import apply_primary_requirement

    claim = _claim(
        status=ClaimStatus.SINGLE_SOURCE,
        evidence=[
            SimpleNamespace(
                evidence_type=EvidenceType.SUPPORTS, source_item=None, source_url="https://medio.test/n"
            ),
            SimpleNamespace(
                evidence_type=EvidenceType.SUPPORTS, source_item=None, source_url="https://otro.test/n"
            ),
        ],
    )
    plan = VerificationPlan(
        verification_target=VerificationTarget.JUDICIAL_RECORD,
        subject=VerificationSubject.JUDICIAL_CASE,
        primary_source_required=True,
    )
    assert (
        apply_primary_requirement(claim, ClaimStatus.SUPPORTED, plan, primary_supports=False)
        == ClaimStatus.SINGLE_SOURCE
    )
    assert (
        apply_primary_requirement(claim, ClaimStatus.SUPPORTED, plan, primary_supports=True)
        == ClaimStatus.SUPPORTED
    )


def test_reprints_and_blogs_are_not_independent_corroboration() -> None:
    from app.services.verification_policy import independent_support_count

    excerpt = "la funcionaria británica accedió a información estratégica de las fuerzas armadas argentinas"
    first = SimpleNamespace(
        evidence_type=EvidenceType.SUPPORTS,
        excerpt=excerpt,
        source_item=None,
        source_url="https://laderecha.test/nota",
    )
    reprint = SimpleNamespace(
        evidence_type=EvidenceType.SUPPORTS,
        excerpt=excerpt,
        source_item=None,
        source_url="https://otrodiario.test/copia",
    )
    blog = SimpleNamespace(
        evidence_type=EvidenceType.SUPPORTS,
        excerpt="texto distinto en un blog personal sobre el mismo tema de la denuncia",
        source_item=None,
        source_url="https://algo.blogspot.com/post",
    )
    claim = _claim(evidence=[first, reprint, blog])
    assert independent_support_count(claim) == 1


def test_postgres_safe_json_strips_nul() -> None:
    from app.core.text import postgres_safe_json

    payload = {"reason": "actualizaci\u0000ón", "nested": [{"excerpt": "IPC 2,1%\x00"}]}
    cleaned = postgres_safe_json(payload)
    assert "\x00" not in cleaned["reason"]
    assert "\x00" not in cleaned["nested"][0]["excerpt"]

