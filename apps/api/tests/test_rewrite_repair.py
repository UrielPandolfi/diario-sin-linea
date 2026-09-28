"""Reparaciones de redacción que pueden entrar al ciclo de reescritura. Sin DB ni proveedores."""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.schemas.auditing import (
    AuditIssue,
    AuditIssueAction,
    AuditIssueReason,
    AuditIssueSeverity,
    AuditIssueType,
)
from app.schemas.writing import ArticleContext
from app.services.audit_policy import (
    rewrite_targets,
    structural_blocks_rewrite,
    structural_issue_is_repairable,
)
from app.services.audit_service import AuditService

CENTRAL = "El presidente tiene previsto aterrizar en el aeropuerto el martes a las nueve y media."
EXTRA = "El presidente participará de la asamblea general de las naciones unidas."
CAVEAT = "El regreso del jueves figura en un solo reporte y no tiene corroboración independiente."

_RESTRICTED = {
    "attribution_required": True,
    "categorical_allowed": False,
    "headline_unattributed_allowed": False,
    "independent_confirmation_language_allowed": False,
}
_OPEN = {
    "attribution_required": False,
    "categorical_allowed": True,
    "headline_unattributed_allowed": True,
    "independent_confirmation_language_allowed": True,
}


def _issue(
    text: str,
    *,
    claim_id: str | None,
    reason: AuditIssueReason,
    severity: AuditIssueSeverity = AuditIssueSeverity.HIGH,
    claim_ref: str | None = "headline",
) -> AuditIssue:
    return AuditIssue(
        type=AuditIssueType.UNSUPPORTED_CLAIM,
        severity=severity,
        text=text,
        explanation="hallazgo de prueba",
        suggested_fix="reescritura",
        reason=reason,
        action=AuditIssueAction.REWRITE,
        claim_id=claim_id,
        claim_ref=claim_ref,
    )


def _article(headline: str, summary: str, body: str) -> SimpleNamespace:
    return SimpleNamespace(headline=headline, summary=summary, body=body, body_blocks=[])


def _decision(
    status: str,
    *,
    state: str = "complete",
    rendering: dict | None = None,
    origins: list[str] | None = None,
    documents_supporting: int = 0,
    documents_qualifying: int = 0,
    documents_contradicting: int = 0,
) -> dict:
    return {
        "status": status,
        "evaluation_state": state,
        "support_basis": {
            "kind": "single_report",
            "documents_supporting": documents_supporting,
            "documents_qualifying": documents_qualifying,
            "documents_contradicting": documents_contradicting,
            "information_origins": list(origins or []),
        },
        "public_rendering": rendering,
        "verified_scope": CENTRAL if state == "complete" else None,
        "unsupported_scope": None,
    }


def _covered_snapshot(
    *,
    extra_state: str = "skipped",
    extra_rendering: dict | None = None,
    extra_origins: list[str] | None = None,
    documents_supporting: int = 0,
    documents_qualifying: int = 0,
    coverage_gap: bool = False,
    expected: list[dict] | None = None,
    central_rendering: dict | None = None,
    central_origins: list[str] | None = None,
    sources: list[dict] | None = None,
    evidence: list[dict] | None = None,
) -> dict:
    central_id = "central-1"
    extra_id = "extra-1"
    if expected is None:
        expected = [
            {
                "proposition": CENTRAL,
                "role": "existence",
                "match": "equivalent",
                "match_claim_id": central_id,
            }
        ]
    context: dict = {"claim_refs": {"C1": central_id, "C2": extra_id}}
    if sources is not None:
        context["sources"] = sources
        context["single_source_claims"] = [
            {
                "id": central_id,
                "canonical_text": CENTRAL,
                "status": "SINGLE_SOURCE",
                "evidence": evidence or [],
            }
        ]
    return {
        "evaluated_claims": [
            {"id": central_id, "canonical_text": CENTRAL, "status": "SUPPORTED", "importance": "HIGH"},
            {"id": extra_id, "canonical_text": EXTRA, "status": "OUTDATED", "importance": "LOW"},
        ],
        "decision_by_claim_id": {
            central_id: _decision(
                "SUPPORTED",
                rendering=central_rendering if central_rendering is not None else _OPEN,
                origins=central_origins if central_origins is not None else ["reporting:ejemplo.test"],
            ),
            extra_id: _decision(
                "OUTDATED",
                state=extra_state,
                rendering=extra_rendering,
                origins=extra_origins,
                documents_supporting=documents_supporting,
                documents_qualifying=documents_qualifying,
            ),
        },
        "coverage": {
            "coverage_gap": coverage_gap,
            "verification_incomplete": False,
            "expected_central": expected,
        },
        "article_context": context,
    }


def _attribution_issue(claim_id: str = "central-1") -> AuditIssue:
    return _issue(CENTRAL, claim_id=claim_id, reason=AuditIssueReason.SURFACE_ATTRIBUTION)


def _trim_issue() -> AuditIssue:
    return _issue(
        f"{CENTRAL} {EXTRA}",
        claim_id="extra-1",
        reason=AuditIssueReason.SURFACE_CONTRACT_INCOMPLETE,
        claim_ref="lead",
    )


def _story_with_extra() -> SimpleNamespace:
    lead = f"{CENTRAL} {EXTRA}"
    return _article(CENTRAL, CENTRAL, f"{lead}\n\n{CENTRAL}")


def test_omitted_attribution_on_a_complete_publishable_claim_can_be_rewritten() -> None:
    snapshot = _covered_snapshot(
        central_rendering=_RESTRICTED,
        central_origins=["reporting:lanacion.com.ar"],
    )
    article = _article(CENTRAL, CENTRAL, CENTRAL)
    issue = _attribution_issue()
    categorical = _issue(CENTRAL, claim_id="central-1", reason=AuditIssueReason.SURFACE_CATEGORICAL)
    assert structural_issue_is_repairable(issue, article, snapshot)
    assert structural_issue_is_repairable(categorical, article, snapshot)
    assert structural_blocks_rewrite([issue, categorical], article=article, snapshot=snapshot) is False
    assert structural_blocks_rewrite([issue]) is True
    targets = rewrite_targets([issue], article, snapshot)
    assert targets[0]["repair"] == "attribution"
    assert targets[0]["fragment"] == CENTRAL
    assert targets[0]["contract"]["information_origins"] == ["reporting:lanacion.com.ar"]
    assert targets[0]["contract"]["public_rendering"]["attribution_required"] is True


def test_documents_and_a_linked_source_identify_provenance_without_origins() -> None:
    snapshot = _covered_snapshot(
        central_rendering=_RESTRICTED,
        central_origins=[],
        sources=[{"ref": 1, "name": "La Nación"}],
        evidence=[{"source_ref": 1, "evidence_type": "supports"}],
    )
    snapshot["decision_by_claim_id"]["central-1"]["support_basis"]["documents_supporting"] = 2
    snapshot["decision_by_claim_id"]["central-1"]["support_basis"]["information_origins"] = []
    article = _article(CENTRAL, CENTRAL, CENTRAL)
    issue = _attribution_issue()
    assert structural_issue_is_repairable(issue, article, snapshot)
    assert rewrite_targets([issue], article, snapshot)[0]["contract"]["named_sources"] == ["La Nación"]


def test_a_source_list_without_recorded_support_does_not_identify_provenance() -> None:
    snapshot = _covered_snapshot(
        central_rendering=_RESTRICTED,
        central_origins=[],
        sources=[{"ref": 1, "name": "La Nación"}],
        evidence=[{"source_ref": 1, "evidence_type": "supports"}],
    )
    article = _article(CENTRAL, CENTRAL, CENTRAL)
    assert structural_blocks_rewrite([_attribution_issue()], article=article, snapshot=snapshot) is True


def test_open_or_incomplete_contract_does_not_repair_attribution() -> None:
    article = _article(CENTRAL, CENTRAL, CENTRAL)
    open_snapshot = _covered_snapshot(central_rendering=_OPEN, central_origins=["reporting:ejemplo.test"])
    skipped = _covered_snapshot(central_rendering=None, central_origins=["reporting:ejemplo.test"])
    skipped["decision_by_claim_id"]["central-1"]["evaluation_state"] = "skipped"
    skipped["decision_by_claim_id"]["central-1"]["public_rendering"] = None
    assert structural_blocks_rewrite([_attribution_issue()], article=article, snapshot=open_snapshot) is True
    assert structural_blocks_rewrite([_attribution_issue()], article=article, snapshot=skipped) is True


def test_accessory_detail_outside_established_coverage_can_be_trimmed() -> None:
    snapshot = _covered_snapshot()
    article = _story_with_extra()
    issue = _trim_issue()
    assert structural_issue_is_repairable(issue, article, snapshot)
    assert structural_blocks_rewrite([issue], article=article, snapshot=snapshot) is False
    assert rewrite_targets([issue], article, snapshot)[0]["repair"] == "accessory_trim"


def test_empty_expected_central_does_not_prove_coverage() -> None:
    snapshot = _covered_snapshot(expected=[])
    article = _story_with_extra()
    assert structural_blocks_rewrite([_trim_issue()], article=article, snapshot=snapshot) is True


def test_unevaluated_central_and_coverage_gap_keep_the_block() -> None:
    article = _story_with_extra()
    unevaluated = _covered_snapshot(
        expected=[
            {
                "proposition": EXTRA,
                "role": "existence",
                "match": "equivalent",
                "match_claim_id": "extra-1",
            }
        ]
    )
    gap = _covered_snapshot(coverage_gap=True)
    assert structural_blocks_rewrite([_trim_issue()], article=article, snapshot=unevaluated) is True
    assert structural_blocks_rewrite([_trim_issue()], article=article, snapshot=gap) is True


def test_a_material_caveat_is_not_an_accessory_detail() -> None:
    article = _story_with_extra()
    qualified = _covered_snapshot(documents_qualifying=1)
    assert structural_blocks_rewrite([_trim_issue()], article=article, snapshot=qualified) is True

    caveat_id = "caveat-1"
    snapshot = _covered_snapshot()
    snapshot["evaluated_claims"].append(
        {"id": caveat_id, "canonical_text": CAVEAT, "status": "SINGLE_SOURCE", "importance": "HIGH"}
    )
    snapshot["decision_by_claim_id"][caveat_id] = _decision("SINGLE_SOURCE", rendering=_RESTRICTED, origins=["reporting:ejemplo.test"])
    only_caveat = _article(CENTRAL, CENTRAL, CAVEAT)
    issue = _issue(CAVEAT, claim_id="extra-1", reason=AuditIssueReason.SURFACE_CONTRACT_INCOMPLETE, claim_ref="lead")
    assert structural_blocks_rewrite([issue], article=only_caveat, snapshot=snapshot) is True


def test_a_coverage_block_prevents_rewrite_even_if_attribution_is_repairable() -> None:
    snapshot = _covered_snapshot(central_rendering=_RESTRICTED, central_origins=["reporting:lanacion.com.ar"])
    article = _article(CENTRAL, CENTRAL, CENTRAL)
    attribution = _attribution_issue()
    central = _issue("núcleo sin evaluar", claim_id=None, reason=AuditIssueReason.CENTRAL_UNCOVERED, claim_ref=None)
    assert structural_issue_is_repairable(attribution, article, snapshot)
    assert structural_blocks_rewrite([attribution, central], article=article, snapshot=snapshot) is True
    independent = _issue(CENTRAL, claim_id="central-1", reason=AuditIssueReason.SURFACE_INDEPENDENT_LANGUAGE)
    assert structural_blocks_rewrite([attribution, independent], article=article, snapshot=snapshot) is True


def test_repairable_issues_still_stop_at_the_existing_rewrite_cap() -> None:
    assert Settings.model_fields["max_audit_rewrite_cycles"].default == 2
    source = inspect.getsource(AuditService._run)
    assert source.index("if rewrites >= cap") < source.index("schema=ArticleDraft")
    assert source.count("rewrites = 0") == 1
    assert "rewrites += 1" in source
    snapshot = _covered_snapshot(central_rendering=_RESTRICTED, central_origins=["reporting:ejemplo.test"])
    article = _article(CENTRAL, CENTRAL, CENTRAL)
    issue = _attribution_issue()
    cap = 2
    rewrites = 0
    audits = 0
    while True:
        audits += 1
        assert structural_blocks_rewrite([issue], article=article, snapshot=snapshot) is False
        if rewrites >= cap:
            reason = "cap_exhausted"
            break
        rewrites += 1
        if audits > 6:
            raise AssertionError("la reparación abrió otro bucle")
    assert rewrites == cap
    assert audits == cap + 1
    assert reason == "cap_exhausted"


def test_rewrite_prompt_asks_for_minimal_repairs_of_this_version() -> None:
    snapshot = _covered_snapshot(central_rendering=_RESTRICTED, central_origins=["reporting:ejemplo.test"])
    article = _article(CENTRAL, CENTRAL, CENTRAL)
    context = ArticleContext.model_validate(
        {"event": {"event_id": "e", "event_type": "otro", "working_title": "Suceso"}}
    )
    prompt = AuditService._rewrite_user_prompt(None, context, article, [_attribution_issue()], snapshot=snapshot)
    assert "cambios mínimos" in prompt.casefold()
    assert "verified_scope" in prompt
    assert "unsupported_scope" in prompt
    assert "categorical_allowed" in prompt
    assert "No inventes emisores" in prompt
    assert "reporting:ejemplo.test" in prompt
    assert '"repair": "attribution"' in prompt


def _export_snapshot(article_id: str) -> dict:
    name = "sin_linea_revision_bloqueos.json"
    here = Path(__file__).resolve()
    candidates = [here.parents[index] / name for index in (3, 2, 1) if len(here.parents) > index]
    candidates.append(Path("/audit-export.json"))
    path = next((item for item in candidates if item.is_file()), None)
    if path is None:
        pytest.skip("export de bloqueos ausente")
    payload = json.loads(path.read_text(encoding="utf-8"))
    for event in payload["sucesos"]:
        article = event["articulo"]
        if article["article_id"] != article_id:
            continue
        return event["versiones"][0]["snapshot_historico"]
    raise AssertionError(f"artículo ausente en el export: {article_id}")


def test_formosa_attribution_is_eligible_and_milei_scope_gap_is_not() -> None:
    formosa = _export_snapshot("fe26e42b-85ea-4a4c-9714-694bfb77b6a4")
    milei = _export_snapshot("f2b4ac65-72af-4aa9-ac25-3640d22a7070")
    formosa_claim = "b791e4d5-5b26-4301-98b0-01ee6cf5e542"
    milei_claim = "8837f7f9-e3a3-4cef-abe0-089826664a30"
    article = _article("titular", "bajada", "cuerpo")
    attribution = _issue("denuncia sin atribución", claim_id=formosa_claim, reason=AuditIssueReason.SURFACE_ATTRIBUTION)
    assert structural_issue_is_repairable(attribution, article, formosa)
    coverage = _issue("núcleo", claim_id=None, reason=AuditIssueReason.CENTRAL_UNCOVERED, claim_ref=None)
    assert structural_blocks_rewrite([attribution, coverage], article=article, snapshot=formosa) is True

    incomplete = _issue(
        "viaje para participar en la asamblea",
        claim_id=milei_claim,
        reason=AuditIssueReason.SURFACE_CONTRACT_INCOMPLETE,
        claim_ref="lead",
    )
    assert milei["coverage"]["expected_central"] == []
    assert structural_issue_is_repairable(incomplete, article, milei) is False
    assert structural_blocks_rewrite([incomplete], article=article, snapshot=milei) is True
