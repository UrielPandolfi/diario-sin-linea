from types import SimpleNamespace

import pytest

from app.domain.enums import ClaimImportance, ClaimStatus, EvidenceType
from app.schemas.claims import ExtractedClaim, ExtractedEvidence
from app.schemas.claims import ClaimExtractionBatch, ClaimResolutionBatch, ClaimResolutionItem
from app.schemas.evidence_comparison import EvidenceComparison, Measurement
from app.schemas.verification import VerificationEvidence, VerificationPlan, VerificationResult, TemporalScope, VerificationTarget
from app.services.claim_meaning import preserve_extracted_meaning
from app.services.claim_coverage import proposition_role_for
from app.services.evidence_comparison import (
    conflict_comparability,
    mixed_evidence_supports_conflict,
    valid_contradiction,
)
from app.services.verification_plan import heuristic_plan, refine_plan, build_verification_queries, try_resolve_numeric_comparison
from app.services.verification_service import VerificationService, _PacketSource
from app.services.claim_service import ClaimService
from app.models import PipelineRun
from app.domain.enums import PipelineStatus
from app.providers.fakes import FakeStructuredLLM, FakeSearchProvider
from sqlalchemy import select
from tests.test_verification import _source, _item, _event, _claim, _evidence


ORIGINAL = "The Economist reconoció que el Gobierno logró bajar la inflación desde niveles cercanos al 13% mensual hasta alrededor del 2%."
SOURCE = "The Economist reconoció que el Gobierno logró bajar la inflación desde niveles cercanos al 13% mensual antes de su llegada al poder hasta alrededor del 2%, además de alcanzar superávits fiscales y reducir significativamente la pobreza."
STATISTIC = "El IPC mensual de Argentina estuvo alrededor del 2% en agosto de 2026."


def _observation(value="25", period="agosto de 2026", scope="Argentina", indicator="IPC"):
    return f"El {indicator} mensual de {scope} registró {value}% en {period}."


def _comparison(value="25", period="agosto de 2026", scope="Argentina", indicator="IPC"):
    return EvidenceComparison(
        proposition="statistic", claim_fragment=STATISTIC,
        evidence_fragment=_observation(value, period, scope, indicator), basis="incompatible_value",
        claim_measurement=Measurement(indicator="IPC", unit="% mensual", scope="Argentina", period="agosto de 2026", value="2"),
        evidence_measurement=Measurement(indicator=indicator, unit="% mensual", scope=scope, period=period, value=value),
        approximation="incompatible",
        approximation_reason="25% es más de doce veces 2%; esta observación mensual no es una aproximación ni un redondeo de 2%.",
        reason="El documento informa un valor incompatible para el mismo índice, ámbito y mes.",
    )


def test_original_preserves_attribution_trajectory_and_source():
    raw = ExtractedClaim(canonical_text=ORIGINAL, claim_type="hecho", subject="Gobierno de Javier Milei",
                         normalized_value="2", unit="porcentaje",
                         evidence=[ExtractedEvidence(source_ref=1, evidence_type=EvidenceType.SUPPORTS, excerpt=SOURCE)])
    source = SimpleNamespace(clean_text=SOURCE, url="https://derechadiario.com.ar/politica/nota")
    result = preserve_extracted_meaning(raw, [source])
    assert result.claim_type == "declaracion"
    assert result.subject == "The Economist"
    assert result.normalized_value is None
    assert "cercanos al 13% mensual antes de su llegada al poder hasta alrededor del 2%" in result.object_text
    assert result.evidence[0].source_ref == 1
    assert result.evidence[0].excerpt == SOURCE
    assert proposition_role_for(result).value == "utterance"
    # A separately extracted statistic keeps BOTH endpoints in its identity.
    economic = raw.model_copy(update={"canonical_text": SOURCE.split("reconoció que ")[1]})
    economic = preserve_extracted_meaning(economic, [source])
    assert economic.normalized_value is None
    assert "13%" in economic.object_text and "2%" in economic.object_text


def test_declaration_and_underlying_fact_keep_distinct_assertion_keys():
    from app.services.claim_service import assertion_key_for, comparison_key_for

    spoken = preserve_extracted_meaning(
        ExtractedClaim(
            canonical_text="Aguilar anunció que el ciclo lectivo comenzará el 2 de marzo.",
            claim_type="declaracion",
        ),
        [],
    )
    official = ExtractedClaim(
        canonical_text="El ciclo lectivo comenzará el 2 de marzo.",
        claim_type="hecho",
        subject="El ciclo lectivo",
        predicate="comenzará",
        object_text="el 2 de marzo",
    )
    assert assertion_key_for(spoken) != assertion_key_for(official)
    assert comparison_key_for(spoken).startswith("prop|")
    assert "d:2 marzo" in comparison_key_for(spoken)


def test_plan_cannot_replace_attribution_or_drop_material_terms():
    claim = SimpleNamespace(canonical_text=ORIGINAL, claim_type="hecho", occurred_at=None,
                            importance=ClaimImportance.HIGH, status=ClaimStatus.SINGLE_SOURCE, evidence=[])
    fallback = heuristic_plan(claim)
    plan = refine_plan(VerificationPlan(verification_target=VerificationTarget.OFFICIAL_STATISTICS,
                                        search_terms=["Inflación", "Milei", "dos cifras", "13%", "2%"],
                                        year_hint=2026), fallback, claim=claim)
    assert plan.verification_target == VerificationTarget.PRIMARY_STATEMENT
    assert plan.temporal_scope == TemporalScope.UNKNOWN_PERIOD
    assert plan.year_hint is None
    queries = build_verification_queries(claim, plan, [])
    assert all("13%" in q and "2%" in q and "The Economist" in q and "dos cifras" not in q for q in queries)
    assert try_resolve_numeric_comparison(claim, []) is None


@pytest.mark.parametrize("value", ["1,7", "1,9"])
def test_rounding_compatible_values_cannot_disprove_even_if_model_says_so(value):
    claim = SimpleNamespace(canonical_text=STATISTIC, claim_type="cifra")
    valid, reason = valid_contradiction(claim, _comparison(value), body=_observation(value), body_source="extracted_html")
    assert not valid and reason == "compatible_rounding"


@pytest.mark.parametrize("field,value", [("period", "junio de 2026"), ("scope", "Córdoba"), ("scope", "nacional"), ("indicator", "IPC núcleo")])
def test_other_period_scope_or_indicator_is_not_refutation(field, value):
    comparison = _comparison(**{field: value})
    claim = SimpleNamespace(canonical_text=STATISTIC, claim_type="cifra")
    valid, reason = valid_contradiction(claim, comparison, body=comparison.evidence_fragment, body_source="extracted_html")
    assert not valid and reason == "different_" + field


def test_missing_coordinates_or_original_document_cannot_disprove():
    claim = SimpleNamespace(canonical_text=STATISTIC, claim_type="cifra")
    comparison = _comparison()
    assert not valid_contradiction(claim, comparison, body=comparison.evidence_fragment, body_source="search_snippet")[0]
    comparison.claim_measurement.scope = ""
    assert not valid_contradiction(claim, comparison, body=comparison.evidence_fragment, body_source="extracted_html")[0]


def test_model_cannot_hide_index_category_in_measurement_label():
    claim = SimpleNamespace(canonical_text=STATISTIC, claim_type="cifra")
    comparison = _comparison(indicator="IPC núcleo")
    comparison.evidence_measurement.indicator = "IPC"
    assert valid_contradiction(claim, comparison, body=comparison.evidence_fragment, body_source="extracted_html") == (False, "missing_measurement_coordinates")


def test_outside_rounding_cell_without_contextual_approximation_is_inconclusive():
    claim = SimpleNamespace(canonical_text=STATISTIC, claim_type="cifra")
    comparison = _comparison("2,6")
    comparison.approximation = "unknown"
    comparison.approximation_reason = None
    assert valid_contradiction(claim, comparison, body=comparison.evidence_fragment, body_source="extracted_html") == (False, "approximation_unresolved")


@pytest.mark.parametrize("as_statement,expected", [(False, ClaimStatus.DISPROVEN), (True, ClaimStatus.UNCERTAIN)])
def test_final_resolution_requires_comparable_proposition(db_session, as_statement, expected):
    text = "The Economist reconoció que " + STATISTIC if as_statement else STATISTIC
    source = _source(db_session)
    item = _item(db_session, source.id, url="https://ejemplo.test/ipc", title="IPC agosto", body=_observation(), content_hash="comparison")
    item.metadata_json = {"body_source": "extracted_html", "fetch_ok": True}
    event = _event(db_session, item)
    claim = _claim(db_session, event, text=text, claim_type="declaracion" if as_statement else "cifra",
                   importance=ClaimImportance.HIGH, status=ClaimStatus.SINGLE_SOURCE, subject="The Economist" if as_statement else "IPC")
    comparison = _comparison()
    result = VerificationResult(status=ClaimStatus.DISPROVEN, reason="El modelo afirma que es falso.",
                                evidence=[VerificationEvidence(source_ref=1, evidence_type=EvidenceType.CONTRADICTS,
                                           excerpt=_observation(), comparison=comparison)])
    packet = [_PacketSource(ref=1, url=item.url, title=item.title, snippet=item.clean_text, item=item, body_source="extracted_html")]
    VerificationService(db_session)._apply_result(event, claim, packet, result, VerificationPlan(), [], False)
    assert claim.status == expected
    assert claim.evidence[0].evidence_type == (EvidenceType.CONTRADICTS if not as_statement else EvidenceType.MENTIONS)


def test_model_disproven_without_any_comparison_is_blocked(db_session):
    source = _source(db_session)
    item = _item(db_session, source.id, url="https://ejemplo.test/ipc", title="IPC", body=_observation("1,7"), content_hash="unjustified")
    event = _event(db_session, item)
    claim = _claim(db_session, event, text=ORIGINAL, claim_type="hecho", importance=ClaimImportance.HIGH, status=ClaimStatus.DISPROVEN)
    packet = [_PacketSource(ref=1, url=item.url, title=item.title, snippet=item.clean_text, item=item, body_source="extracted_html")]
    service = VerificationService(db_session)
    result = VerificationResult(status=ClaimStatus.DISPROVEN, evidence=[VerificationEvidence(source_ref=1, evidence_type=EvidenceType.CONTRADICTS, excerpt=item.clean_text)])
    *_, decision = service._apply_result(event, claim, packet, result, VerificationPlan(), [], False)
    assert claim.status == ClaimStatus.UNCERTAIN
    assert decision.unresolved
    assert "contradicción pertinente" in decision.final_reason


@pytest.mark.parametrize("value", ["1,7", "1,9"])
def test_monthly_point_cannot_support_entire_trajectory(value):
    service = object.__new__(VerificationService)
    claim = SimpleNamespace(canonical_text=ORIGINAL.split("reconoció que ")[1], claim_type="cifra")
    row = VerificationEvidence(source_ref=1, evidence_type=EvidenceType.SUPPORTS, excerpt=_observation(value))
    assert service._admit_relation(claim, None, row, EvidenceType.SUPPORTS)[0] == EvidenceType.QUALIFIES


def test_raw_supports_demoted_to_qualifies_is_not_assessment_support():
    from app.schemas.verification import CheapClaimEvidenceAssessment, CheapEvidenceJudgement, EvidenceJudgementType
    from app.services.verification_plan import assessment_has_support

    service = object.__new__(VerificationService)
    service._comparison_checks = []
    claim = SimpleNamespace(canonical_text=ORIGINAL.split("reconoció que ")[1], claim_type="cifra")
    excerpt = _observation("1,7")
    row = VerificationEvidence(source_ref=1, evidence_type=EvidenceType.SUPPORTS, excerpt=excerpt)
    admitted, _ = service._admit_relation(claim, None, row, EvidenceType.SUPPORTS)
    assert admitted == EvidenceType.QUALIFIES
    assessment = CheapClaimEvidenceAssessment(
        judgements=[
            CheapEvidenceJudgement(
                source_ref=1,
                relation=EvidenceJudgementType.SUPPORTS,
                excerpt=excerpt,
            )
        ]
    )
    assert assessment_has_support(assessment, admission_checks=service._comparison_checks) is False
    assert service._comparison_checks[0]["requested"] == "SUPPORTS"
    assert service._comparison_checks[0]["admitted"] == "QUALIFIES"


def test_utterance_content_excerpt_is_not_admitted_support():
    from app.schemas.verification import CheapClaimEvidenceAssessment, CheapEvidenceJudgement, EvidenceJudgementType
    from app.services.verification_plan import assessment_has_support

    service = object.__new__(VerificationService)
    service._comparison_checks = []
    claim = SimpleNamespace(
        canonical_text="Pérez afirmó que el costo será de 40.000 millones.",
        claim_type="declaracion",
    )
    rejected = VerificationEvidence(
        source_ref=1,
        evidence_type=EvidenceType.SUPPORTS,
        excerpt="el costo será de 40.000 millones",
    )
    assert service._admit_relation(claim, None, rejected, EvidenceType.SUPPORTS)[0] == EvidenceType.MENTIONS
    raw = CheapClaimEvidenceAssessment(
        judgements=[
            CheapEvidenceJudgement(
                source_ref=1,
                relation=EvidenceJudgementType.SUPPORTS,
                excerpt=rejected.excerpt,
            )
        ]
    )
    assert assessment_has_support(raw, admission_checks=service._comparison_checks) is False
    service._comparison_checks = []
    speech = VerificationEvidence(
        source_ref=1,
        evidence_type=EvidenceType.SUPPORTS,
        excerpt="Pérez afirmó que el costo será de 40.000 millones.",
    )
    assert service._admit_relation(claim, None, speech, EvidenceType.SUPPORTS)[0] == EvidenceType.SUPPORTS
    admitted = CheapClaimEvidenceAssessment(
        judgements=[
            CheapEvidenceJudgement(
                source_ref=1,
                relation=EvidenceJudgementType.SUPPORTS,
                excerpt=speech.excerpt,
            )
        ]
    )
    assert assessment_has_support(admitted, admission_checks=service._comparison_checks) is True


def test_targeted_reextraction_and_verification_preserve_id_and_history(db_session):
    source = _source(db_session, name="La Derecha Diario", domain="derechadiario.com.ar")
    item = _item(db_session, source.id, url="https://derechadiario.com.ar/politica/nota", title="La entrevista",
                 body=SOURCE, content_hash="original")
    item.metadata_json = {"body_source": "extracted_html", "fetch_ok": True}
    event = _event(db_session, item)
    claim = _claim(db_session, event, text=ORIGINAL, claim_type="hecho", importance=ClaimImportance.HIGH,
                   status=ClaimStatus.DISPROVEN, subject="Gobierno de Javier Milei", normalized_value="2")
    sibling = _claim(db_session, event, text="Otra proposición", claim_type="hecho", importance=ClaimImportance.HIGH,
                     status=ClaimStatus.SUPPORTED)
    old = PipelineRun(event_id=event.id, stage="verification", status=PipelineStatus.SUCCESS,
                      metadata_json={"historical": "DISPROVEN"})
    db_session.add(old)
    db_session.flush()
    original_id = claim.id
    extractor = FakeStructuredLLM({"ClaimExtractionBatch": ClaimExtractionBatch(claims=[
        ExtractedClaim(canonical_text="Según La Derecha Diario, " + ORIGINAL, normalized_value="2",
                       evidence=[ExtractedEvidence(source_ref=1, evidence_type=EvidenceType.SUPPORTS, excerpt=SOURCE)])
    ])})
    resolver = FakeStructuredLLM({"ClaimResolutionBatch": ClaimResolutionBatch(items=[
        ClaimResolutionItem(claim_ref=1, status=ClaimStatus.SINGLE_SOURCE)
    ])})
    extracted = ClaimService(db_session, extractor_llm=extractor, resolver_llm=resolver).resolve(event.id, trigger="admin", claim_id=claim.id)
    assert "error" not in extracted
    assert claim.id == original_id and "antes de su llegada al poder" in claim.canonical_text
    assert claim.subject == "The Economist"
    assert extracted["claim_before"]["status"] == "DISPROVEN"
    assert "derechadiario.com.ar" in extractor.user_prompts[0]
    llm = FakeStructuredLLM({"VerificationResult": VerificationResult(status=ClaimStatus.SINGLE_SOURCE,
         evidence=[VerificationEvidence(source_ref=1, evidence_type=EvidenceType.SUPPORTS, excerpt=SOURCE)])})
    verified = VerificationService(db_session, llm=llm, search=FakeSearchProvider()).verify(event.id, trigger="admin", claim_id=claim.id)
    assert "error" not in verified
    assert claim.status == ClaimStatus.SINGLE_SOURCE and sibling.status == ClaimStatus.SUPPORTED
    assert old.metadata_json == {"historical": "DISPROVEN"}
    runs = db_session.scalars(select(PipelineRun).where(PipelineRun.event_id == event.id)).all()
    assert len(runs) == 3
    assert verified["selected"] == [{"claim_id": str(claim.id), "reasons": ["explicit_recheck"]}]
    assert verified["packets"][str(claim.id)][0]["url"] == item.url
    assert verified["model_results"][str(claim.id)]["status"] == "SINGLE_SOURCE"


def test_explicit_recheck_bypasses_disproven_veto_without_forcing_status(db_session):
    source = _source(db_session)
    item = _item(db_session, source.id, url="https://ejemplo.test/n", title="Nota", body=SOURCE, content_hash="recheck")
    event = _event(db_session, item)
    claim = _claim(db_session, event, text=ORIGINAL, claim_type="hecho", importance=ClaimImportance.HIGH, status=ClaimStatus.DISPROVEN)
    llm = FakeStructuredLLM({"VerificationResult": VerificationResult(status=ClaimStatus.DISPROVEN)})
    result = VerificationService(db_session, llm=llm, search=FakeSearchProvider()).verify(event.id, trigger="admin", claim_id=claim.id)
    assert "error" not in result
    assert llm.calls == ["VerificationResult"]
    assert claim.status == ClaimStatus.UNCERTAIN


def test_displayed_excerpt_must_contain_the_admitted_contradiction():
    claim = SimpleNamespace(canonical_text=STATISTIC, claim_type="cifra")
    comparison = _comparison()
    row = VerificationEvidence(source_ref=1, evidence_type=EvidenceType.CONTRADICTS,
                               excerpt=_observation("1,7"), comparison=comparison)
    src = SimpleNamespace(item=SimpleNamespace(clean_text=comparison.evidence_fragment + " " + row.excerpt), body_source="extracted_html")
    service = object.__new__(VerificationService)
    assert service._admit_relation(claim, src, row, row.evidence_type) == (EvidenceType.MENTIONS, False)
    assert service._comparison_checks[-1]["reason"] == "comparison_not_in_cited_excerpt"


def test_qualifies_partial_claim_does_not_promote_full_proposition(db_session):
    from app.schemas.editorial_evidence import ReasonCode

    established = "El decreto elimina el régimen"
    missing = "entra en vigencia mañana"
    text = f"{established} y {missing}"
    source = _source(db_session)
    item = _item(
        db_session,
        source.id,
        url="https://ejemplo.test/decreto",
        title="Decreto",
        body=established,
        content_hash="partial-c3",
    )
    item.metadata_json = {"body_source": "extracted_html", "fetch_ok": True}
    event = _event(db_session, item)
    claim = _claim(
        db_session,
        event,
        text=text,
        claim_type="hecho",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.SINGLE_SOURCE,
    )
    comparison = EvidenceComparison(
        proposition="other",
        claim_fragment=established,
        evidence_fragment=established,
        basis="partial_support",
        reason="solo el acto, no la vigencia",
    )
    result = VerificationResult(
        status=ClaimStatus.SINGLE_SOURCE,
        reason="parcial",
        evidence=[
            VerificationEvidence(
                source_ref=1,
                evidence_type=EvidenceType.QUALIFIES,
                excerpt=established,
                comparison=comparison,
            )
        ],
    )
    packet = [
        _PacketSource(
            ref=1,
            url=item.url,
            title=item.title,
            snippet=item.clean_text,
            item=item,
            body_source="extracted_html",
        )
    ]
    service = VerificationService(db_session)
    *_, decision = service._apply_result(event, claim, packet, result, VerificationPlan(), [], False)
    assert claim.status != ClaimStatus.SUPPORTED
    assert decision.reason_code is ReasonCode.PARTIAL_SUPPORT
    assert decision.verified_scope == established
    assert decision.unsupported_scope is None
    assert decision.verified_scope != text
    assert decision.final_reason == "La evidencia solo sostiene parte de la proposición."
    assert decision.public_rendering is not None
    assert decision.public_rendering.categorical_allowed is False
    assert decision.public_rendering.independent_confirmation_language_allowed is False


def _ns_claim(**overrides):
    payload = {
        "canonical_text": "Se registraron 4 heridos",
        "claim_type": "cifra",
        "subject": "accidente",
        "predicate": "cantidad_heridos",
        "object_text": "4 heridos",
        "normalized_value": "4",
        "unit": "personas",
        "occurred_at": None,
        "evidence": [],
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def test_conflict_comparability_requires_shared_coordinates():
    from datetime import datetime, timezone

    when = datetime(2026, 8, 24, 16, 0, tzinfo=timezone.utc)
    four = _ns_claim(occurred_at=when)
    six = _ns_claim(canonical_text="Se registraron 6 heridos", object_text="6 heridos", normalized_value="6", occurred_at=when)
    assert conflict_comparability(four, six) == (True, "comparable_proposition")
    later = _ns_claim(canonical_text="Se confirmaron 6 heridos", object_text="6 heridos", normalized_value="6", occurred_at=datetime(2026, 8, 24, 17, 0, tzinfo=timezone.utc))
    assert conflict_comparability(four, later)[0] is False
    august = _ns_claim(canonical_text="El IPC de agosto de 2026 fue 2%", subject="IPC", predicate="variacion", object_text="2% en agosto de 2026", normalized_value="2", unit="%", occurred_at=when)
    june = _ns_claim(canonical_text="El IPC de junio de 2026 fue 3%", subject="IPC", predicate="variacion", object_text="3% en junio de 2026", normalized_value="3", unit="%", occurred_at=when)
    assert conflict_comparability(august, june) == (False, "different_period")
    monthly = _ns_claim(canonical_text="La inflación mensual fue 2%", subject="inflacion", predicate="variacion", object_text="2% mensual", normalized_value="2", unit="%", occurred_at=when)
    yoy = _ns_claim(canonical_text="La inflación interanual fue 19%", subject="inflacion", predicate="variacion", object_text="19% interanual", normalized_value="19", unit="%", occurred_at=when)
    assert conflict_comparability(monthly, yoy) == (False, "different_unit")
    missing = _ns_claim(occurred_at=None, canonical_text="Se registraron 4 heridos")
    missing_other = _ns_claim(canonical_text="Se registraron 6 heridos", object_text="6 heridos", normalized_value="6", occurred_at=None)
    assert conflict_comparability(missing, missing_other) == (False, "missing_period")
    spoken = _ns_claim(canonical_text="Pérez dijo que el valor era 15", claim_type="declaracion", subject="Pérez", predicate="dijo", object_text="el valor era 15", unit="")
    factual = _ns_claim(canonical_text="El valor es 19", claim_type="cifra", subject="valor", predicate="es", object_text="19", normalized_value="19")
    assert conflict_comparability(spoken, factual) == (False, "utterance_versus_content")
    other_speaker = _ns_claim(canonical_text="Gómez dijo que el valor era 19", claim_type="declaracion", subject="Gómez", predicate="dijo", object_text="el valor era 19", unit="", normalized_value="19")
    assert conflict_comparability(spoken, other_speaker) == (False, "distinct_speech_acts")
    decree_yes = SimpleNamespace(canonical_text="El decreto elimina X", claim_type="documento", subject="decreto", predicate="elimina", object_text="X", normalized_value="si", unit="", occurred_at=None)
    decree_no = SimpleNamespace(canonical_text="El decreto no elimina X", claim_type="documento", subject="decreto", predicate="elimina", object_text="no X", normalized_value="no", unit="", occurred_at=None)
    assert conflict_comparability(decree_yes, decree_no) == (True, "comparable_proposition")


def test_mixed_evidence_ignores_incomparable_contradicts():
    claim = _ns_claim(
        canonical_text="El IPC de agosto de 2026 fue 2%",
        subject="IPC",
        predicate="variacion",
        object_text="2% en agosto de 2026",
        normalized_value="2",
        unit="%",
        evidence=[
            SimpleNamespace(evidence_type=EvidenceType.SUPPORTS, excerpt="IPC de agosto de 2026 fue 2%"),
            SimpleNamespace(evidence_type=EvidenceType.CONTRADICTS, excerpt="IPC de junio de 2026 fue 25%"),
        ],
    )
    assert mixed_evidence_supports_conflict(claim) is False
    negation = _ns_claim(
        evidence=[
            SimpleNamespace(evidence_type=EvidenceType.SUPPORTS, excerpt="4 heridos"),
            SimpleNamespace(evidence_type=EvidenceType.CONTRADICTS, excerpt="desmintieron que hubiera heridos"),
        ]
    )
    assert mixed_evidence_supports_conflict(negation) is True


def test_verified_reconciler_requires_comparability(db_session):
    from datetime import datetime, timezone

    when = datetime(2026, 8, 24, 16, 0, tzinfo=timezone.utc)
    source_a = _source(db_session, name="A", domain="a.test", feed_url="https://a.test/rss.xml")
    source_b = _source(db_session, name="B", domain="b.test", feed_url="https://b.test/rss.xml")
    item_a = _item(db_session, source_a.id, url="https://a.test/n", title="A", body="agosto 2%", content_hash="ha")
    item_b = _item(db_session, source_b.id, url="https://b.test/n", title="B", body="junio 25%", content_hash="hb")
    event = _event(db_session, item_a)
    from app.services.event_service import EventService
    from app.domain.enums import EventSourceRelation

    EventService(db_session).attach_source(event, item_b.id, relation_type=EventSourceRelation.ADDITIONAL)
    august = _claim(
        db_session, event, text="El IPC de agosto de 2026 fue 2%", claim_type="cifra",
        importance=ClaimImportance.HIGH, status=ClaimStatus.SUPPORTED, subject="IPC", predicate="variacion",
        object_text="2% en agosto de 2026", normalized_value="2", unit="%", occurred_at=when,
    )
    june = _claim(
        db_session, event, text="El IPC de junio de 2026 fue 25%", claim_type="cifra",
        importance=ClaimImportance.HIGH, status=ClaimStatus.SUPPORTED, subject="IPC", predicate="variacion",
        object_text="25% en junio de 2026", normalized_value="25", unit="%", occurred_at=when,
    )
    _evidence(db_session, august, item_a, excerpt="agosto 2%")
    _evidence(db_session, june, item_b, excerpt="junio 25%")
    payload = {
        "selected": [{"claim_id": str(august.id), "reasons": ["policy:cifra"]}],
        "skipped_search": [],
        "primary_source_supports_claim": {str(august.id): True},
        "sol": [{"claim_id": str(august.id), "status_after": "SUPPORTED", "unresolved": False}],
        "comparison_checks": {},
        "decision_by_claim_id": {},
    }
    VerificationService(db_session, llm=FakeStructuredLLM(), search=FakeSearchProvider([]))._reconcile_verified_competitors(
        [august, june], payload
    )
    assert august.status == ClaimStatus.SUPPORTED
    assert june.status == ClaimStatus.SUPPORTED


def test_rejected_c6_contradiction_is_not_conflict_basis(db_session):
    source = _source(db_session)
    item = _item(db_session, source.id, url="https://ejemplo.test/ipc", title="IPC", body=_observation("25"), content_hash="c6")
    item.metadata_json = {"body_source": "extracted_html", "fetch_ok": True}
    event = _event(db_session, item)
    claim = _claim(
        db_session, event, text=STATISTIC, claim_type="cifra", importance=ClaimImportance.HIGH,
        status=ClaimStatus.SINGLE_SOURCE, subject="IPC", predicate="variacion", object_text="2%", unit="% mensual",
    )
    _evidence(db_session, claim, item, excerpt=STATISTIC)
    comparison = _comparison("25", period="junio de 2026")
    result = VerificationResult(
        status=ClaimStatus.CONFLICTING,
        unresolved=True,
        reason="el modelo ve otro mes",
        evidence=[VerificationEvidence(source_ref=1, evidence_type=EvidenceType.CONTRADICTS, excerpt=_observation("25", period="junio de 2026"), comparison=comparison)],
    )
    packet = [_PacketSource(ref=1, url=item.url, title=item.title, snippet=item.clean_text, item=item, body_source="extracted_html")]
    service = VerificationService(db_session)
    service._comparison_checks = []
    *_, decision = service._apply_result(event, claim, packet, result, VerificationPlan(), [], False)
    assert claim.status != ClaimStatus.CONFLICTING
    assert claim.status != ClaimStatus.SUPPORTED
    assert decision.evaluation_state.value == "complete"
    assert any(row["requested"] == "CONTRADICTS" and row["admitted"] != "CONTRADICTS" for row in service._comparison_checks)


def test_verified_reconcile_keeps_disproven_requirements(db_session):
    source = _source(db_session)
    item = _item(db_session, source.id, url="https://ejemplo.test/ipc", title="IPC", body=_observation(), content_hash="disproven")
    item.metadata_json = {"body_source": "extracted_html", "fetch_ok": True}
    event = _event(db_session, item)
    claim = _claim(db_session, event, text=STATISTIC, claim_type="cifra", importance=ClaimImportance.HIGH, status=ClaimStatus.SINGLE_SOURCE, subject="IPC")
    comparison = _comparison()
    result = VerificationResult(
        status=ClaimStatus.DISPROVEN,
        reason="falso",
        evidence=[VerificationEvidence(source_ref=1, evidence_type=EvidenceType.CONTRADICTS, excerpt=_observation(), comparison=comparison)],
    )
    packet = [_PacketSource(ref=1, url=item.url, title=item.title, snippet=item.clean_text, item=item, body_source="extracted_html")]
    VerificationService(db_session)._apply_result(event, claim, packet, result, VerificationPlan(), [], False)
    assert claim.status == ClaimStatus.DISPROVEN


def test_missing_period_does_not_promote_supported_after_discard(db_session):
    from datetime import datetime, timezone
    from app.schemas.editorial_evidence import EvaluationState, ReasonCode

    source = _source(db_session)
    item = _item(db_session, source.id, url="https://ejemplo.test/n", title="N", body="heridos", content_hash="h1")
    event = _event(db_session, item)
    four = _claim(
        db_session, event, text="Se registraron 4 heridos", claim_type="cifra", importance=ClaimImportance.HIGH,
        status=ClaimStatus.CONFLICTING, subject="accidente", predicate="cantidad_heridos", object_text="4 heridos",
        normalized_value="4", unit="personas",
    )
    six = _claim(
        db_session, event, text="Se registraron 6 heridos", claim_type="cifra", importance=ClaimImportance.HIGH,
        status=ClaimStatus.CONFLICTING, subject="accidente", predicate="cantidad_heridos", object_text="6 heridos",
        normalized_value="6", unit="personas",
    )
    _evidence(db_session, four, item, excerpt="4 heridos")
    _evidence(db_session, six, item, excerpt="6 heridos")
    payload = {
        "comparison_checks": {},
        "decision_by_claim_id": {
            str(four.id): {
                "claim_id": str(four.id),
                "status": ClaimStatus.CONFLICTING.value,
                "evaluation_state": EvaluationState.COMPLETE.value,
                "reason_code": ReasonCode.CONFLICTING_COMPARABLE_EVIDENCE.value,
            }
        },
        "plans": {},
        "primary_source_supports_claim": {},
        "sol": [],
    }
    VerificationService(db_session, llm=FakeStructuredLLM(), search=FakeSearchProvider([]))._reconcile_verified_competitors(
        [four, six], payload
    )
    assert four.status != ClaimStatus.CONFLICTING
    assert six.status != ClaimStatus.CONFLICTING
    assert four.status != ClaimStatus.SUPPORTED
    assert six.status != ClaimStatus.SUPPORTED
    decision = payload["decision_by_claim_id"][str(four.id)]
    assert decision["evaluation_state"] == EvaluationState.COMPLETE.value
    assert decision["status"] != ClaimStatus.SUPPORTED.value


def test_c7_reconcile_does_not_change_published_v1(db_session):
    from datetime import datetime, timezone
    from app.domain.enums import EventSourceRelation
    from app.services.event_service import EventService
    from app.services.feed_ranking import compact_public_claims
    from tests.editorial_snapshot import persist_version_snapshot
    from app.services.article_service import ArticleService
    from app.schemas import ArticleCreate

    when = datetime(2026, 8, 24, 16, 0, tzinfo=timezone.utc)
    source_a = _source(db_session, name="A", domain="a.test", feed_url="https://a.test/rss.xml")
    source_b = _source(db_session, name="B", domain="b.test", feed_url="https://b.test/rss.xml")
    item_a = _item(db_session, source_a.id, url="https://a.test/n", title="A", body="4 heridos", content_hash="ha")
    item_b = _item(db_session, source_b.id, url="https://b.test/n", title="B", body="6 heridos", content_hash="hb")
    event = _event(db_session, item_a)
    EventService(db_session).attach_source(event, item_b.id, relation_type=EventSourceRelation.ADDITIONAL)
    four = _claim(
        db_session, event, text="Se registraron 4 heridos", claim_type="cifra", importance=ClaimImportance.HIGH,
        status=ClaimStatus.SINGLE_SOURCE, subject="accidente", predicate="cantidad_heridos", object_text="4 heridos",
        normalized_value="4", unit="personas", occurred_at=when,
    )
    six = _claim(
        db_session, event, text="Se registraron 6 heridos", claim_type="cifra", importance=ClaimImportance.HIGH,
        status=ClaimStatus.SUPPORTED, subject="accidente", predicate="cantidad_heridos", object_text="6 heridos",
        normalized_value="6", unit="personas", occurred_at=when,
    )
    _evidence(db_session, four, item_a, excerpt="4 heridos")
    _evidence(db_session, six, item_b, excerpt="6 heridos")
    article, _created = ArticleService(db_session).create_draft(
        ArticleCreate(
            event_id=event.id,
            headline="Hubo heridos",
            summary="Hubo heridos, según las fuentes.",
            body="Según las fuentes, hubo heridos.",
            body_blocks=[{"type": "paragraph", "segments": [{"text": "Según las fuentes, hubo heridos.", "claim_ids": [str(four.id)]}]}],
        )
    )
    persist_version_snapshot(db_session, event, article)
    from app.models import PipelineRun
    from sqlalchemy.orm.attributes import flag_modified
    from app.schemas.editorial_evidence import ReasonCode, Demotion, SupportKind

    writing = db_session.scalars(
        select(PipelineRun).where(PipelineRun.event_id == event.id, PipelineRun.stage == "writing")
    ).first()
    snap = dict(writing.metadata_json["evidence_snapshot"])
    cid = str(four.id)
    snap["decision_by_claim_id"] = {
        cid: {
            "claim_id": cid,
            "status": ClaimStatus.SINGLE_SOURCE.value,
            "evaluation_state": "complete",
            "reason_code": ReasonCode.SINGLE_KNOWN_ORIGIN.value,
            "public_rendering": {
                "attribution_required": True,
                "categorical_allowed": False,
                "headline_unattributed_allowed": False,
                "independent_confirmation_language_allowed": False,
            },
            "support_basis": {"known_independent_count": 1, "demotion": Demotion.INSUFFICIENT_INDEPENDENCE.value, "kind": SupportKind.SINGLE_REPORT.value},
        }
    }
    writing.metadata_json = {**writing.metadata_json, "evidence_snapshot": snap}
    flag_modified(writing, "metadata_json")
    db_session.flush()
    before = compact_public_claims(db_session, event, freeze_to_version=1)
    payload = {
        "selected": [{"claim_id": str(six.id), "reasons": ["policy:cifra"]}],
        "primary_source_supports_claim": {str(six.id): True},
        "sol": [{"claim_id": str(six.id), "status_after": "SUPPORTED", "unresolved": False}],
        "comparison_checks": {},
        "decision_by_claim_id": {},
    }
    VerificationService(db_session, llm=FakeStructuredLLM(), search=FakeSearchProvider([]))._reconcile_verified_competitors(
        [four, six], payload
    )
    after = compact_public_claims(db_session, event, freeze_to_version=1)
    assert four.status == ClaimStatus.CONFLICTING
    assert after[0]["status"] == before[0]["status"] == ClaimStatus.SINGLE_SOURCE.value
    assert after[0]["reason_code"] == before[0]["reason_code"]
    assert after[0]["presentation"]["verification_label"] == before[0]["presentation"]["verification_label"]


def test_c7_does_not_add_verification_llm_calls(db_session):
    from datetime import datetime, timezone
    from app.domain.enums import EventSourceRelation
    from app.services.event_service import EventService

    when = datetime(2026, 8, 24, 16, 0, tzinfo=timezone.utc)
    source_a = _source(db_session, name="A", domain="a.test", feed_url="https://a.test/rss.xml")
    source_b = _source(db_session, name="B", domain="b.test", feed_url="https://b.test/rss.xml")
    item_a = _item(db_session, source_a.id, url="https://a.test/n", title="A", body="4 heridos", content_hash="ha")
    item_b = _item(db_session, source_b.id, url="https://b.test/n", title="B", body="6 heridos", content_hash="hb")
    event = _event(db_session, item_a)
    EventService(db_session).attach_source(event, item_b.id, relation_type=EventSourceRelation.ADDITIONAL)
    four = _claim(
        db_session, event, text="Se registraron 4 heridos", claim_type="cifra", importance=ClaimImportance.HIGH,
        status=ClaimStatus.SUPPORTED, subject="accidente", predicate="cantidad_heridos", object_text="4 heridos",
        normalized_value="4", unit="personas", occurred_at=when,
    )
    six = _claim(
        db_session, event, text="Se registraron 6 heridos", claim_type="cifra", importance=ClaimImportance.HIGH,
        status=ClaimStatus.SUPPORTED, subject="accidente", predicate="cantidad_heridos", object_text="6 heridos",
        normalized_value="6", unit="personas", occurred_at=when,
    )
    _evidence(db_session, four, item_a, excerpt="4 heridos")
    _evidence(db_session, six, item_b, excerpt="6 heridos")
    llm = FakeStructuredLLM()
    llm.calls = ["sentinel"]
    VerificationService(db_session, llm=llm, search=FakeSearchProvider([]))._reconcile_verified_competitors(
        [four, six],
        {
            "selected": [{"claim_id": str(six.id), "reasons": ["policy:cifra"]}],
            "primary_source_supports_claim": {str(six.id): True},
            "sol": [{"claim_id": str(six.id), "status_after": "SUPPORTED", "unresolved": False}],
            "comparison_checks": {},
            "decision_by_claim_id": {},
        },
    )
    assert llm.calls == ["sentinel"]
