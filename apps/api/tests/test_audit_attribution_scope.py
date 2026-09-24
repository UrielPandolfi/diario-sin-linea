"""Atribución con alcance, correspondencia de claims y excepción de titular. Sin DB ni proveedores."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from app.schemas.auditing import (
    ArticleAuditResult,
    AuditIssue,
    AuditIssueAction,
    AuditIssueReason,
    AuditIssueSeverity,
    AuditIssueType,
)
from app.services.audit_policy import (
    HEADLINE_TOLERANCE_NOTE,
    apply_headline_attribution_tolerance,
    certainty_findings,
    drop_mismatched_llm_claim_links,
    headline_omission_is_tolerated,
    merge_audit_result,
    structural_blocks_rewrite,
    structural_findings,
)
from app.services.surface_validation import (
    _assertion_attributed,
    _sentence_spans,
    assertions_are_attributed,
)

def _export_path() -> Path:
    name = "sin_linea_revision_bloqueos.json"
    here = Path(__file__).resolve()
    candidates = [here.parents[2] / name, Path("/audit-export.json")]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]


_EXPORT = _export_path()
_BLOCKING = {AuditIssueSeverity.HIGH, AuditIssueSeverity.MEDIUM}


def _article(headline: str, summary: str, lead: str) -> SimpleNamespace:
    return SimpleNamespace(
        headline=headline,
        summary=summary,
        body=lead,
        body_blocks=[{"type": "paragraph", "segments": [{"text": lead, "claim_ids": []}]}],
    )


def _rendering(**overrides: bool) -> dict:
    base = {
        "categorical_allowed": False,
        "attribution_required": True,
        "headline_unattributed_allowed": False,
        "independent_confirmation_language_allowed": False,
    }
    base.update(overrides)
    return base


def _snapshot(claim_id: str, text: str, *, status: str = "SINGLE_SOURCE", numbers_text: str | None = None) -> dict:
    scope = numbers_text or text
    return {
        "claims_fingerprint": "fp",
        "coverage_run_id": "cov",
        "verification_run_id": "ver",
        "evaluated_claims": [{"id": claim_id, "canonical_text": text, "status": status, "importance": "HIGH"}],
        "decision_by_claim_id": {
            claim_id: {
                "status": status,
                "evaluation_state": "complete",
                "verified_scope": scope,
                "unsupported_scope": None,
                "support_basis": {"kind": "single_report", "documents_supporting": 1},
                "public_rendering": _rendering(),
            }
        },
        "article_context": {"claim_refs": {"C1": claim_id}},
        "coverage": {"expected_central": [], "coverage_gap": False},
        "verification": {"based_on_claim_run_id": "cov", "expected_central": []},
    }


def _issue(text: str, *, claim_id: str | None, claim_ref: str | None, reason: AuditIssueReason, severity: AuditIssueSeverity = AuditIssueSeverity.HIGH) -> AuditIssue:
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


def test_sentence_spans_keep_decimals_initials_and_do_not_split_on_spaces() -> None:
    text = "El Dr. Pérez anunció 40.000 millones. El Ministerio pidió, según reportes periodísticos, que se investigue."
    spans = _sentence_spans(text)
    assert len(spans) == 2
    assert "Dr. Pérez" in text[spans[0][0] : spans[0][1]]
    assert "40.000" in text[spans[0][0] : spans[0][1]]
    assert "según reportes" in text[spans[1][0] : spans[1][1]]


def test_attribution_markers_cover_the_clause_that_holds_the_claim() -> None:
    salary = "Reportes periodísticos sostienen que Esteche cobró el sueldo."
    two = "Dos informes periodísticos sostienen que Esteche cobró el sueldo."
    formosa = (
        "Diputadas provinciales cuestionaron un video y el Ministerio pidió, "
        "según reportes periodísticos, que la provincia investigue lo ocurrido."
    )
    maneuver = "Un reporte de El País atribuye al juez el procesamiento de siete iraníes y un libanés."
    claim_salary = "Esteche cobró el sueldo"
    claim_formosa = "el Ministerio pidió que la provincia investigue lo ocurrido"
    claim_maneuver = "el juez procesó a siete iraníes y un libanés"
    assert _assertion_attributed(salary, claim_salary)
    assert _assertion_attributed(two, claim_salary)
    assert _assertion_attributed(formosa, claim_formosa)
    assert _assertion_attributed(maneuver, claim_maneuver)
    negative = "Según el informe ocurrió el incendio. El ministro confirmó la cifra de 40 detenidos."
    assert not _assertion_attributed(negative, "El ministro confirmó la cifra de 40 detenidos")
    assert not assertions_are_attributed(negative)
    assert assertions_are_attributed(salary)


def test_claim_ref_alias_and_uuid_are_resolved_before_keeping_a_link() -> None:
    headline = "Milei llegó a Nueva York para la asamblea."
    arrival = "0b0ae24f-05ef-4fb9-9c5d-1c875c6b4636"
    returned = "4703a87e-3e96-4fc3-b013-039d012abb1d"
    snapshot = {
        "evaluated_claims": [
            {"id": arrival, "canonical_text": "Milei llegó a Nueva York para la asamblea de la ONU.", "status": "SUPPORTED"},
            {"id": returned, "canonical_text": "Milei regresó de Nueva York tras la asamblea.", "status": "SINGLE_SOURCE"},
        ],
        "decision_by_claim_id": {},
        "article_context": {"claim_refs": {"C2": returned, "C9": arrival}},
    }
    wrong = _issue(headline, claim_id=None, claim_ref="C2", reason=AuditIssueReason.SINGLE_AS_CORROBORATED)
    kept = drop_mismatched_llm_claim_links([wrong], snapshot)
    assert kept == []
    right = _issue(headline, claim_id=None, claim_ref=arrival, reason=AuditIssueReason.SINGLE_AS_CORROBORATED)
    assert drop_mismatched_llm_claim_links([right], snapshot)
    surface_label = _issue(headline, claim_id=None, claim_ref="headline", reason=AuditIssueReason.SEMANTIC_SHIFT)
    assert drop_mismatched_llm_claim_links([surface_label], snapshot)
    unresolved = _issue(headline, claim_id=None, claim_ref="C99", reason=AuditIssueReason.SEMANTIC_SHIFT)
    assert drop_mismatched_llm_claim_links([unresolved], snapshot)


def test_same_fact_with_a_different_number_is_not_dropped() -> None:
    claim_id = "ef-17"
    text = "La causa tiene 17 detenidos y tres prófugos."
    altered = "La causa tiene 27 detenidos y tres prófugos."
    snapshot = _snapshot(claim_id, "La investigación registra 17 detenidos y tres prófugos.")
    issue = _issue(altered, claim_id=claim_id, claim_ref="C1", reason=AuditIssueReason.SEMANTIC_SHIFT)
    kept = drop_mismatched_llm_claim_links([issue], snapshot)
    assert kept and kept[0].claim_id == claim_id
    assert altered in kept[0].text


def test_synthetic_headline_omission_is_low_and_does_not_request_rewrite() -> None:
    claim_id = "agg-42"
    headline = "El operativo dejó 42 detenidos y 8 prófugos"
    summary = "Según un informe policial, el operativo dejó 42 detenidos y 8 prófugos."
    lead = "Un informe policial informó que el operativo dejó 42 detenidos y 8 prófugos."
    article = _article(headline, summary, lead)
    snapshot = _snapshot(claim_id, "El operativo dejó 42 detenidos y 8 prófugos.")
    rendering = snapshot["decision_by_claim_id"][claim_id]["public_rendering"]
    before = dict(rendering)
    issues = [
        _issue(headline, claim_id=claim_id, claim_ref="headline", reason=AuditIssueReason.SURFACE_ATTRIBUTION),
        _issue(headline, claim_id=claim_id, claim_ref="headline", reason=AuditIssueReason.SURFACE_CATEGORICAL),
        _issue(headline, claim_id=claim_id, claim_ref="C1", reason=AuditIssueReason.SINGLE_AS_CORROBORATED),
        _issue(headline, claim_id=None, claim_ref="C1", reason=AuditIssueReason.SINGLE_AS_CORROBORATED),
    ]
    result = merge_audit_result(
        ArticleAuditResult(passed=False, issues=issues),
        structural=[],
        article=article,
        snapshot=snapshot,
    )
    assert result.passed is True
    assert not structural_blocks_rewrite(result.issues)
    lows = [issue for issue in result.issues if issue.severity == AuditIssueSeverity.LOW and issue.text == headline]
    assert lows
    assert all(HEADLINE_TOLERANCE_NOTE in (issue.explanation or "") for issue in lows)
    assert all(issue.suggested_fix is None for issue in lows)
    assert rendering == before
    assert rendering["headline_unattributed_allowed"] is False
    assert rendering["categorical_allowed"] is False


def test_guilt_headline_and_refuted_or_altered_claims_stay_blocking() -> None:
    claim_id = "guilt"
    headline = "Pérez asesinó a la víctima y hay 12 detenidos"
    summary = "Según un informe, Pérez asesinó a la víctima y hay 12 detenidos."
    article = _article(headline, summary, summary)
    snapshot = _snapshot(claim_id, "Pérez asesinó a la víctima y hay 12 detenidos.")
    issue = _issue(headline, claim_id=claim_id, claim_ref="headline", reason=AuditIssueReason.SURFACE_ATTRIBUTION)
    assert headline_omission_is_tolerated(issue, article, snapshot) is False
    result = merge_audit_result(
        ArticleAuditResult(passed=False, issues=[issue]),
        structural=[],
        article=article,
        snapshot=snapshot,
    )
    assert result.passed is False
    assert any(row.severity in _BLOCKING for row in result.issues)

    independent = _issue(
        "Fuentes independientes confirmaron 42 detenidos.",
        claim_id=claim_id,
        claim_ref="summary",
        reason=AuditIssueReason.SURFACE_INDEPENDENT_LANGUAGE,
    )
    summary_article = _article(
        "Hay 42 detenidos",
        "Fuentes independientes confirmaron 42 detenidos.",
        "Según un informe, hay 42 detenidos.",
    )
    blocked = merge_audit_result(
        ArticleAuditResult(passed=False, issues=[independent]),
        structural=[],
        article=summary_article,
        snapshot=_snapshot(claim_id, "Hay 42 detenidos."),
    )
    assert any(row.reason == AuditIssueReason.SURFACE_INDEPENDENT_LANGUAGE and row.severity in _BLOCKING for row in blocked.issues)

    refuted = _snapshot(claim_id, "Hay 42 detenidos.", status="DISPROVEN")
    refuted_issue = _issue("Hay 42 detenidos", claim_id=claim_id, claim_ref="headline", reason=AuditIssueReason.SURFACE_ATTRIBUTION)
    assert headline_omission_is_tolerated(refuted_issue, summary_article, refuted) is False


def test_central_uncovered_is_not_demoted() -> None:
    article = _article("Titular sin atribución", "Según un informe, hay 15 casos.", "Un informe informó que hay 15 casos.")
    snapshot = _snapshot("c", "Hay 15 casos.")
    structural = [
        _issue("Titular sin atribución", claim_id=None, claim_ref=None, reason=AuditIssueReason.CENTRAL_UNCOVERED)
    ]
    result = merge_audit_result(None, structural=structural, article=article, snapshot=snapshot)
    assert result.passed is False
    assert structural_blocks_rewrite(result.issues)


def test_attribution_on_another_sentence_does_not_clear_a_categorical_claim() -> None:
    article = _article(
        "El incendio dejó 30 heridos",
        "Según el informe ocurrió un incendio. El ministro confirmó que hay 30 heridos.",
        "El ministro confirmó que hay 30 heridos.",
    )
    snapshot = _snapshot("c30", "Hay 30 heridos confirmados por el ministro.")
    issues = certainty_findings(article, snapshot)
    assert any(issue.claim_ref == "summary" and issue.severity in _BLOCKING for issue in issues)


def _versions(payload: dict) -> list[dict]:
    rows = []
    for event in payload.get("sucesos") or []:
        article_id = (event.get("articulo") or {}).get("article_id")
        for version in event.get("versiones") or []:
            audit = (version.get("audit") or {}).get("run") or {}
            meta = audit.get("metadata_json") or {}
            if not meta.get("evidence_snapshot"):
                continue
            rows.append(
                {
                    "article_id": article_id,
                    "version": version.get("version_number"),
                    "situacion": version.get("situacion"),
                    "article": _article(version.get("titular") or "", version.get("bajada") or "", version.get("cuerpo") or ""),
                    "body_blocks": version.get("body_blocks"),
                    "snapshot": meta["evidence_snapshot"],
                    "stored": meta.get("issues") or [],
                    "historical_passed": meta.get("passed"),
                }
            )
    return rows


def _replay(row: dict) -> ArticleAuditResult:
    article = row["article"]
    article.body_blocks = row["body_blocks"]
    stored = [AuditIssue.model_validate(issue) for issue in row["stored"]]
    structural = structural_findings(row["snapshot"], article)
    return merge_audit_result(
        ArticleAuditResult(passed=False, issues=stored),
        structural=structural,
        article=article,
        snapshot=row["snapshot"],
    )


def _blocking(issues: list[AuditIssue]) -> list[AuditIssue]:
    return [issue for issue in issues if issue.severity in _BLOCKING]


def test_exported_versions_follow_the_new_audit_policy() -> None:
    payload = json.loads(_EXPORT.read_text(encoding="utf-8"))
    rows = _versions(payload)
    by_key = {(row["article_id"], row["version"]): row for row in rows}

    florencio = by_key[("88184369-da43-4acf-b600-40e4e9153860", 1)]
    florencio_result = _replay(florencio)
    assert florencio_result.passed is True
    assert not _blocking(florencio_result.issues)
    assert not structural_blocks_rewrite(florencio_result.issues)
    assert any(HEADLINE_TOLERANCE_NOTE in (issue.explanation or "") for issue in florencio_result.issues)
    decision = florencio["snapshot"]["decision_by_claim_id"]["ef994d00-19aa-4c2a-b785-3bf6eb0857db"]
    assert decision["public_rendering"]["headline_unattributed_allowed"] is False
    assert decision["public_rendering"]["categorical_allowed"] is False
    assert decision["status"] == "SINGLE_SOURCE"

    tablada = by_key[("fa0fa66a-8b21-4e8e-9810-6df8e27af83f", 3)]
    tablada_result = _replay(tablada)
    shot = "37f7556a-5db8-4b63-897b-28ecd73ce273"
    assert not any(
        issue.claim_id == shot and issue.claim_ref in {"summary", "lead"} and issue.severity in _BLOCKING
        for issue in tablada_result.issues
    )

    milei = by_key[("f2b4ac65-72af-4aa9-ac25-3640d22a7070", 1)]
    milei_result = _replay(milei)
    returned = "4703a87e-3e96-4fc3-b013-039d012abb1d"
    assert not any(
        (issue.claim_id == returned or issue.claim_ref == returned) and issue.severity in _BLOCKING
        for issue in milei_result.issues
    )


def _signature(issue: dict | AuditIssue) -> tuple[str, str, str]:
    if isinstance(issue, AuditIssue):
        return (issue.reason.value if issue.reason else "", issue.claim_ref or "", issue.claim_id or "")
    return (str(issue.get("reason") or ""), str(issue.get("claim_ref") or ""), str(issue.get("claim_id") or ""))


def replay_report(payload: dict) -> list[str]:
    """Histórico guardado contra la reevaluación determinista. No llama al modelo."""
    lines = ["article | v | situacion | historico_bloqueo | desaparecen | ahora_LOW | siguen_bloqueando | passed_nuevo"]
    for row in _versions(payload):
        stored = row["stored"]
        historical = [issue for issue in stored if issue.get("severity") in {"HIGH", "MEDIUM"}]
        result = _replay(row)
        new_blocking = _blocking(result.issues)
        new_low = [issue for issue in result.issues if issue.severity == AuditIssueSeverity.LOW]
        hist_keys = {_signature(issue) for issue in historical}
        block_keys = {_signature(issue) for issue in new_blocking}
        low_keys = {_signature(issue) for issue in new_low}
        gone = sorted(hist_keys - block_keys - low_keys)
        to_low = sorted(hist_keys & low_keys)
        remain = sorted(block_keys)
        lines.append(
            " | ".join(
                [
                    str(row["article_id"]),
                    str(row["version"]),
                    str(row["situacion"]),
                    str(len(historical)),
                    ", ".join(f"{reason}/{ref}" for reason, ref, _cid in gone) or "-",
                    ", ".join(f"{reason}/{ref}" for reason, ref, _cid in to_low) or "-",
                    ", ".join(f"{reason}/{ref}" for reason, ref, _cid in remain) or "-",
                    str(result.passed),
                ]
            )
        )
    return lines


if __name__ == "__main__":
    data = json.loads(_EXPORT.read_text(encoding="utf-8"))
    print("\n".join(replay_report(data)))
