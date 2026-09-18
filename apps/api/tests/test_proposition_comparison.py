from types import SimpleNamespace

import pytest

from app.domain.enums import ClaimImportance, ClaimStatus, EvidenceType
from app.schemas.claims import ExtractedClaim, ExtractedEvidence
from app.schemas.claims import ClaimExtractionBatch, ClaimResolutionBatch, ClaimResolutionItem
from app.schemas.evidence_comparison import EvidenceComparison, Measurement
from app.schemas.verification import VerificationEvidence, VerificationPlan, VerificationResult, TemporalScope, VerificationTarget
from app.services.claim_meaning import preserve_extracted_meaning
from app.services.claim_coverage import proposition_role_for
from app.services.evidence_comparison import valid_contradiction
from app.services.verification_plan import heuristic_plan, refine_plan, build_verification_queries, try_resolve_numeric_comparison
from app.services.verification_service import VerificationService, _PacketSource
from app.services.claim_service import ClaimService
from app.models import PipelineRun
from app.domain.enums import PipelineStatus
from app.providers.fakes import FakeStructuredLLM, FakeSearchProvider
from sqlalchemy import select
from tests.test_verification import _source, _item, _event, _claim


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
