from __future__ import annotations

from typing import Any

from app.models import Article
from app.schemas.auditing import (
    ArticleAuditResult,
    AuditIssue,
    AuditIssueAction,
    AuditIssueReason,
    AuditIssueSeverity,
    AuditIssueType,
)
from app.schemas.editorial_evidence import CoverageMatch

_EQUIVALENT = CoverageMatch.EQUIVALENT.value
_BLOCKING = {AuditIssueSeverity.HIGH, AuditIssueSeverity.MEDIUM}

_STRUCTURAL_REASONS = {
    AuditIssueReason.CONTRACT_MISSING,
    AuditIssueReason.CONTRACT_UNPAIRED,
    AuditIssueReason.CENTRAL_UNCOVERED,
    AuditIssueReason.CENTRAL_UNVERIFIED,
}

_NEGATION_PREFIXES = (
    "no hay ",
    "no existen ",
    "no está ",
    "no esta ",
    "no quedó ",
    "no quedo ",
    "no se confirm",
    "sin ",
    "tampoco ",
)
_PLURAL_PHRASES = (
    "varias fuentes independientes",
    "múltiples fuentes independientes",
    "multiples fuentes independientes",
    "fuentes independientes coinciden",
    "quedó confirmado por varias fuentes",
    "quedo confirmado por varias fuentes",
)
_EFFECTIVE_PHRASES = (
    "comenzó a regir",
    "comenzo a regir",
    "entra en vigencia",
    "entró en vigencia",
    "entro en vigencia",
    "ya rige",
)
_ATTRIBUTION_MARKERS = (
    "según ",
    "segun ",
    "de acuerdo con",
    "afirmó que",
    "afirmo que",
    "dijo que",
    "sostuvo que",
)


def _issue(
    *,
    issue_type: AuditIssueType,
    reason: AuditIssueReason,
    text: str,
    explanation: str,
    action: AuditIssueAction,
    severity: AuditIssueSeverity = AuditIssueSeverity.HIGH,
    suggested_fix: str | None = None,
    claim_id: str | None = None,
    claim_ref: str | None = None,
) -> AuditIssue:
    return AuditIssue(
        type=issue_type,
        severity=severity,
        text=text,
        explanation=explanation,
        suggested_fix=suggested_fix,
        reason=reason,
        action=action,
        claim_id=claim_id,
        claim_ref=claim_ref,
    )


def _claim_ids_from_blocks(body_blocks: Any) -> list[str]:
    ids: list[str] = []
    if not isinstance(body_blocks, list):
        return ids
    for block in body_blocks:
        if not isinstance(block, dict):
            continue
        for segment in block.get("segments") or []:
            if not isinstance(segment, dict):
                continue
            for raw in segment.get("claim_ids") or []:
                ids.append(str(raw))
    return ids


def _allowed_claim_ids(snapshot: dict[str, Any]) -> set[str]:
    allowed: set[str] = set()
    context = snapshot.get("article_context") if isinstance(snapshot.get("article_context"), dict) else {}
    refs = context.get("claim_refs") if isinstance(context.get("claim_refs"), dict) else {}
    allowed.update(str(value) for value in refs.values())
    for row in snapshot.get("evaluated_claims") or []:
        if isinstance(row, dict) and row.get("claim_id"):
            allowed.add(str(row["claim_id"]))
    for key in snapshot.get("decision_by_claim_id") or {}:
        allowed.add(str(key))
    return allowed


def structural_findings(snapshot: dict[str, Any] | None, article: Article) -> list[AuditIssue]:
    if snapshot is None:
        return [
            _issue(
                issue_type=AuditIssueType.UNSUPPORTED_CLAIM,
                reason=AuditIssueReason.CONTRACT_MISSING,
                text=article.headline,
                explanation="No hay snapshot de evidencia atado a esta versión.",
                action=AuditIssueAction.REVIEW,
            )
        ]

    issues: list[AuditIssue] = []
    context = snapshot.get("article_context") if isinstance(snapshot.get("article_context"), dict) else {}
    verification = context.get("verification") if isinstance(context.get("verification"), dict) else {}
    fingerprint = snapshot.get("claims_fingerprint") or verification.get("claims_fingerprint")
    stale = bool(snapshot.get("stale_verification") or verification.get("stale_verification"))
    verify_id = snapshot.get("verification_run_id") or verification.get("verification_run_id")
    based_on = snapshot.get("based_on_claim_run_id") or verification.get("based_on_claim_run_id")
    coverage_run_id = snapshot.get("coverage_run_id") or verification.get("coverage_run_id")

    if not fingerprint:
        issues.append(
            _issue(
                issue_type=AuditIssueType.UNSUPPORTED_CLAIM,
                reason=AuditIssueReason.CONTRACT_MISSING,
                text=article.headline,
                explanation="El snapshot no tiene claims_fingerprint.",
                action=AuditIssueAction.REVIEW,
            )
        )
    elif stale or not verify_id:
        issues.append(
            _issue(
                issue_type=AuditIssueType.UNSUPPORTED_CLAIM,
                reason=AuditIssueReason.CONTRACT_UNPAIRED,
                text=article.headline,
                explanation="El snapshot no tiene un par claim↔verify vigente.",
                action=AuditIssueAction.REVIEW,
            )
        )
    elif based_on and coverage_run_id and str(based_on) != str(coverage_run_id):
        issues.append(
            _issue(
                issue_type=AuditIssueType.UNSUPPORTED_CLAIM,
                reason=AuditIssueReason.CONTRACT_UNPAIRED,
                text=article.headline,
                explanation="based_on_claim_run_id no coincide con coverage_run_id del snapshot.",
                action=AuditIssueAction.REVIEW,
            )
        )

    coverage = snapshot.get("coverage") if isinstance(snapshot.get("coverage"), dict) else {}
    expected = coverage.get("expected_central") or verification.get("expected_central") or []
    gap = bool(coverage.get("coverage_gap") or verification.get("coverage_gap"))
    unmatched = False
    for row in expected:
        if not isinstance(row, dict):
            continue
        if (row.get("match") or "") != _EQUIVALENT:
            unmatched = True
            break
    if gap or unmatched:
        issues.append(
            _issue(
                issue_type=AuditIssueType.UNSUPPORTED_CLAIM,
                reason=AuditIssueReason.CENTRAL_UNCOVERED,
                text=article.headline,
                explanation="Hay un coverage_gap central sin resolver en el contrato. No se cierra por paráfrasis ni por atribuir.",
                action=AuditIssueAction.REVIEW,
            )
        )

    central_unverified = list(snapshot.get("central_unverified") or verification.get("central_unverified") or [])
    incomplete = bool(snapshot.get("verification_incomplete") or verification.get("verification_incomplete"))
    if central_unverified or incomplete:
        issues.append(
            _issue(
                issue_type=AuditIssueType.UNSUPPORTED_CLAIM,
                reason=AuditIssueReason.CENTRAL_UNVERIFIED,
                text=article.headline,
                explanation="Hay claims centrales o materiales obligatorios pendientes de verificación.",
                action=AuditIssueAction.REVIEW,
                claim_id=central_unverified[0] if central_unverified else None,
            )
        )

    allowed = _allowed_claim_ids(snapshot)
    if allowed:
        for claim_id in _claim_ids_from_blocks(article.body_blocks):
            if claim_id not in allowed:
                issues.append(
                    _issue(
                        issue_type=AuditIssueType.INVALID_CLAIM_MAPPING,
                        reason=AuditIssueReason.INVALID_CLAIM_REF,
                        text=claim_id,
                        explanation="body_blocks referencia un claim que no está en el snapshot de esta versión.",
                        action=AuditIssueAction.REWRITE,
                        claim_id=claim_id,
                    )
                )
    return issues


def structural_blocks_rewrite(issues: list[AuditIssue]) -> bool:
    return any(issue.reason in _STRUCTURAL_REASONS and issue.severity in _BLOCKING for issue in issues)


def blocking_issues(issues: list[AuditIssue]) -> list[AuditIssue]:
    return [issue for issue in issues if issue.severity in _BLOCKING]


def merge_audit_result(
    llm_result: ArticleAuditResult | None,
    structural: list[AuditIssue] | None = None,
) -> ArticleAuditResult:
    llm_issues = list(llm_result.issues) if llm_result is not None else []
    issues = list(structural or []) + llm_issues
    blocking = blocking_issues(issues)
    passed = not blocking
    return ArticleAuditResult(passed=passed, issues=issues, editorial_passed=passed)


def _clause_is_negated(text: str, index: int) -> bool:
    window = text[max(0, index - 36) : index]
    return any(prefix in window for prefix in _NEGATION_PREFIXES)


def _clause_is_attributed(text: str, index: int) -> bool:
    window = text[max(0, index - 48) : index]
    return any(marker in window for marker in _ATTRIBUTION_MARKERS)


def signals_plural_corroboration(text: str) -> bool:
    lowered = (text or "").lower()
    for phrase in _PLURAL_PHRASES:
        index = lowered.find(phrase)
        if index == -1:
            continue
        if _clause_is_negated(lowered, index):
            continue
        return True
    return False


def signals_unattributed_effective_date(text: str) -> bool:
    lowered = (text or "").lower()
    for phrase in _EFFECTIVE_PHRASES:
        index = lowered.find(phrase)
        if index == -1:
            continue
        if _clause_is_negated(lowered, index) or _clause_is_attributed(lowered, index):
            continue
        return True
    return False


def heuristic_signals(article: Article) -> list[str]:
    blob = f"{article.headline}\n{article.summary}\n{article.body}"
    rows: list[str] = []
    if signals_plural_corroboration(blob):
        rows.append("possible_plural_corroboration")
    if signals_unattributed_effective_date(blob):
        rows.append("possible_unattributed_effective_date")
    return rows
