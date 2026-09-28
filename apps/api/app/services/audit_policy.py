from __future__ import annotations

import re
from typing import Any

from app.core.article_body import block_plain_text, split_body_paragraphs
from app.core.text import token_set
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
    AuditIssueReason.SURFACE_ATTRIBUTION,
    AuditIssueReason.SURFACE_CATEGORICAL,
    AuditIssueReason.SURFACE_INDEPENDENT_LANGUAGE,
    AuditIssueReason.HEADLINE_UNCOVERED,
    AuditIssueReason.SURFACE_CONTRACT_INCOMPLETE,
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
    "afirmó",
    "afirmo",
    "dijo que",
    "sostuvo que",
    "señaló que",
    "senalo que",
    "aseguró que",
    "aseguro que",
    "estimó que",
    "estimo que",
    "anunció que",
    "anuncio que",
    "anunció",
    "anuncio ",
    "indicó que",
    "indico que",
    "informó que",
    "informo que",
    "atribu",
    "un informe",
    "el informe",
    "un reporte",
    "el reporte",
    "dos informes",
    "reportes periodísticos",
    "reportes periodisticos",
    "informes periodísticos",
    "informes periodisticos",
    "sostienen que",
    "sostienen ",
    "la cobertura",
    "habría ",
    "habria ",
    "habrían ",
    "habrian ",
)
_SINGLE_LIKE = {"SINGLE_SOURCE", "UNCERTAIN"}
_CLAIM_STOP = {
    "que",
    "del",
    "una",
    "unos",
    "unas",
    "para",
    "con",
    "por",
    "los",
    "las",
    "el",
    "la",
    "de",
    "en",
    "un",
    "al",
    "es",
    "fue",
    "ser",
    "como",
    "su",
    "sus",
}


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
    from app.services.surface_validation import surface_validation_findings

    issues.extend(surface_validation_findings(snapshot, article))
    return issues


_ATTRIBUTION_REPAIR_REASONS = {
    AuditIssueReason.SURFACE_ATTRIBUTION,
    AuditIssueReason.SURFACE_CATEGORICAL,
}
_CONTEXT_CLAIM_KEYS = (
    "confirmed_claims",
    "single_source_claims",
    "conflicting_claims",
    "uncertain_claims",
    "disproven_claims",
    "outdated_claims",
)
_CONTRADICTION_STATUSES = {"CONFLICTING", "DISPROVEN"}
_UNEVALUATED_STATES = {"skipped", "pending", "failed"}


def structural_blocks_rewrite(
    issues: list[AuditIssue],
    article: Article | None = None,
    snapshot: dict[str, Any] | None = None,
) -> bool:
    """True si algún estructural bloqueante no es una reparación de redacción.

    Sin artículo o sin snapshot se cierra en bloqueo: no se infiere elegibilidad.
    La atribución omitida y el recorte de un detalle accesorio pueden entrar al
    ciclo existente. Un bloqueo de cobertura, contrato o centrales lo impide
    aunque haya otro hallazgo reparable. No cambia passed ni el tope de reescrituras.
    """
    return any(_issue_blocks_rewrite(issue, article, snapshot) for issue in issues)


def structural_issue_is_repairable(
    issue: AuditIssue,
    article: Article | None,
    snapshot: dict[str, Any] | None,
) -> bool:
    if issue.reason not in _STRUCTURAL_REASONS or issue.severity not in _BLOCKING:
        return False
    return not _issue_blocks_rewrite(issue, article, snapshot)


def rewrite_targets(
    issues: list[AuditIssue],
    article: Article | None,
    snapshot: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Fragmento, issue y contrato de esta versión para la reescritura."""
    rows: list[dict[str, Any]] = []
    for issue in issues:
        claim, decision, _unresolved = resolve_issue_claim(issue, snapshot)
        if structural_issue_is_repairable(issue, article, snapshot) and issue.reason in _ATTRIBUTION_REPAIR_REASONS:
            repair = "attribution"
        elif (
            structural_issue_is_repairable(issue, article, snapshot)
            and issue.reason == AuditIssueReason.SURFACE_CONTRACT_INCOMPLETE
        ):
            repair = "accessory_trim"
        else:
            repair = "other"
        reason = issue.reason.value if issue.reason is not None else None
        severity = issue.severity.value if issue.severity is not None else None
        contract = _rewrite_contract(claim, decision)
        if isinstance(contract, dict) and isinstance(snapshot, dict):
            claim_id = str(contract.get("claim_id") or issue.claim_id or "")
            contract["named_sources"] = _linked_source_names(snapshot, claim_id)
        rows.append(
            {
                "fragment": issue.text,
                "surface": issue.claim_ref,
                "reason": reason,
                "severity": severity,
                "claim_id": issue.claim_id,
                "repair": repair,
                "contract": contract,
            }
        )
    return rows


def _issue_blocks_rewrite(
    issue: AuditIssue,
    article: Article | None,
    snapshot: dict[str, Any] | None,
) -> bool:
    if issue.reason not in _STRUCTURAL_REASONS or issue.severity not in _BLOCKING:
        return False
    if article is None or not isinstance(snapshot, dict):
        return True
    if issue.reason in _ATTRIBUTION_REPAIR_REASONS and _attribution_repair_eligible(issue, snapshot):
        return False
    if issue.reason == AuditIssueReason.SURFACE_CONTRACT_INCOMPLETE and _accessory_trim_eligible(issue, article, snapshot):
        return False
    return True


def _attribution_repair_eligible(issue: AuditIssue, snapshot: dict[str, Any]) -> bool:
    claim, decision, unresolved = resolve_issue_claim(issue, snapshot)
    if unresolved or not isinstance(decision, dict):
        return False
    from app.schemas.editorial_evidence import EvaluationState, read_evaluation_state, read_public_rendering

    if read_evaluation_state(decision) != EvaluationState.COMPLETE:
        return False
    rendering = read_public_rendering(decision)
    if rendering is None or rendering.attribution_required is not True:
        return False
    claim_id = str(issue.claim_id or "") or _claim_id(claim or {}) or ""
    return _provenance_identifiable(snapshot, claim_id, decision, claim)


def _accessory_trim_eligible(issue: AuditIssue, article: Article, snapshot: dict[str, Any]) -> bool:
    if not (issue.text or "").strip():
        return False
    claim, decision, unresolved = resolve_issue_claim(issue, snapshot)
    if unresolved or not isinstance(decision, dict):
        return False
    from app.schemas.editorial_evidence import EvaluationState, read_evaluation_state, read_public_rendering

    state = read_evaluation_state(decision)
    if state is None or state == EvaluationState.COMPLETE:
        return False
    if state.value not in _UNEVALUATED_STATES:
        return False
    if read_public_rendering(decision) is not None:
        return False
    if _material_contradiction(decision, claim):
        return False
    established, central_ids, central_rows = _core_coverage_established(snapshot)
    if not established:
        return False
    claim_id = str(issue.claim_id or "") or _claim_id(claim or {}) or ""
    if not claim_id or claim_id in central_ids:
        return False
    if not _centrals_remain_outside_fragment(article, snapshot, issue.text or "", central_rows):
        return False
    if _fragment_is_only_material_caveat(article, snapshot, issue.text or ""):
        return False
    return True


def _provenance_identifiable(
    snapshot: dict[str, Any],
    claim_id: str,
    decision: dict[str, Any],
    claim: dict[str, Any] | None,
) -> bool:
    basis = _support_basis(decision, claim)
    if _information_origins(basis):
        return True
    if _positive_int(basis.get("documents_supporting")) and _linked_source_names(snapshot, claim_id):
        return True
    return False


def _support_basis(decision: dict[str, Any] | None, claim: dict[str, Any] | None) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for row in (decision, claim):
        if not isinstance(row, dict):
            continue
        basis = row.get("support_basis")
        if isinstance(basis, dict):
            candidates.append(basis)
    for basis in candidates:
        if _information_origins(basis) or _positive_int(basis.get("documents_supporting")):
            return basis
    return candidates[0] if candidates else {}


def _information_origins(basis: dict[str, Any]) -> list[str]:
    raw = basis.get("information_origins")
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


def _positive_int(value: Any) -> bool:
    try:
        return int(value) > 0
    except (TypeError, ValueError):
        return False


def _material_contradiction(decision: dict[str, Any], claim: dict[str, Any] | None) -> bool:
    status = str(decision.get("status") or "")
    if status in _CONTRADICTION_STATUSES:
        return True
    basis = _support_basis(decision, claim)
    for key in ("documents_qualifying", "documents_contradicting"):
        raw = basis.get(key)
        if raw is None:
            continue
        try:
            if int(raw) > 0:
                return True
        except (TypeError, ValueError):
            return True
    return False


def _coverage_maps(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    coverage = snapshot.get("coverage")
    if isinstance(coverage, dict):
        rows.append(coverage)
    verification = snapshot.get("verification")
    if isinstance(verification, dict):
        rows.append(verification)
    context = snapshot.get("article_context")
    if isinstance(context, dict) and isinstance(context.get("verification"), dict):
        rows.append(context["verification"])
    return rows


def _flag_true(snapshot: dict[str, Any], key: str) -> bool:
    if snapshot.get(key) is True:
        return True
    return any(row.get(key) is True for row in _coverage_maps(snapshot))


def _has_central_unverified(snapshot: dict[str, Any]) -> bool:
    raw = snapshot.get("central_unverified")
    if isinstance(raw, list) and raw:
        return True
    for row in _coverage_maps(snapshot):
        nested = row.get("central_unverified")
        if isinstance(nested, list) and nested:
            return True
    return False


def _expected_central_rows(snapshot: dict[str, Any]) -> list[dict[str, Any]] | None:
    found: list[list[Any]] = []
    for row in _coverage_maps(snapshot):
        if "expected_central" not in row:
            continue
        value = row.get("expected_central")
        if not isinstance(value, list):
            return None
        found.append(value)
    if not found:
        return None
    first = found[0]
    if any(other != first for other in found[1:]):
        return None
    if not all(isinstance(item, dict) for item in first):
        return None
    return first


def _core_coverage_established(
    snapshot: dict[str, Any],
) -> tuple[bool, list[str], list[dict[str, Any]]]:
    """Cobertura central ya registrada. expected_central vacío no alcanza."""
    if (
        _flag_true(snapshot, "coverage_gap")
        or _flag_true(snapshot, "verification_incomplete")
        or _flag_true(snapshot, "stale_verification")
        or _has_central_unverified(snapshot)
    ):
        return False, [], []
    rows = _expected_central_rows(snapshot)
    if not rows:
        return False, [], []
    _claims, decisions, _refs = _snapshot_claim_index(snapshot)
    from app.schemas.editorial_evidence import EvaluationState, read_evaluation_state, read_public_rendering

    ids: list[str] = []
    for row in rows:
        match = str(row.get("match") or "")
        if match != _EQUIVALENT:
            return False, [], []
        cid = str(row.get("match_claim_id") or "")
        if not cid:
            return False, [], []
        decision = decisions.get(cid)
        if not isinstance(decision, dict) or read_evaluation_state(decision) != EvaluationState.COMPLETE:
            return False, [], []
        if read_public_rendering(decision) is None:
            return False, [], []
        if str(decision.get("status") or "") in _CONTRADICTION_STATUSES:
            return False, [], []
        ids.append(cid)
    return True, ids, rows


def _article_texts(article: Article) -> list[str]:
    texts: list[str] = []
    for value in article_surface_map(article).values():
        if value.strip():
            texts.append(value.strip())
    for part in split_body_paragraphs(article.body or ""):
        if part.strip():
            texts.append(part.strip())
    blocks = article.body_blocks if isinstance(getattr(article, "body_blocks", None), list) else []
    for block in blocks:
        plain = (block_plain_text(block) or "").strip()
        if plain:
            texts.append(plain)
    return texts


def _normalized(text: str) -> str:
    return " ".join((text or "").split())


def _claim_for_match(snapshot: dict[str, Any], claim_id: str, row: dict[str, Any]) -> dict[str, Any]:
    claims, _decisions, _refs = _snapshot_claim_index(snapshot)
    claim = claims.get(claim_id)
    if isinstance(claim, dict) and (claim.get("canonical_text") or claim.get("text")):
        return claim
    proposition = str(row.get("proposition") or "").strip()
    if proposition:
        return {"id": claim_id, "canonical_text": proposition}
    return claim or {"id": claim_id}


def _texts_state_claim(texts: list[str], claim: dict[str, Any], decision: dict[str, Any] | None) -> bool:
    from app.services.surface_validation import asserted_link

    return any(asserted_link(text, claim, decision) == "equivalent" for text in texts)


def _centrals_remain_outside_fragment(
    article: Article,
    snapshot: dict[str, Any],
    fragment: str,
    central_rows: list[dict[str, Any]],
) -> bool:
    remaining = [text for text in _article_texts(article) if _normalized(text) != _normalized(fragment)]
    _claims, decisions, _refs = _snapshot_claim_index(snapshot)
    for row in central_rows:
        cid = str(row.get("match_claim_id") or "")
        claim = _claim_for_match(snapshot, cid, row)
        if not _texts_state_claim(remaining, claim, decisions.get(cid)):
            return False
    return True


def _fragment_is_only_material_caveat(article: Article, snapshot: dict[str, Any], fragment: str) -> bool:
    """La salvedad atribuida solo vive en el fragmento que se recortaría."""
    from app.schemas.editorial_evidence import EvaluationState, read_evaluation_state, read_public_rendering

    claims, decisions, _refs = _snapshot_claim_index(snapshot)
    others = [text for text in _article_texts(article) if _normalized(text) != _normalized(fragment)]
    for cid, decision in decisions.items():
        if not isinstance(decision, dict) or read_evaluation_state(decision) != EvaluationState.COMPLETE:
            continue
        rendering = read_public_rendering(decision)
        if rendering is None or rendering.attribution_required is not True:
            continue
        claim = claims.get(cid) or {"id": cid}
        if not _texts_state_claim([fragment], claim, decision):
            continue
        if not _texts_state_claim(others, claim, decision):
            return True
    return False


def _linked_source_names(snapshot: dict[str, Any], claim_id: str) -> list[str]:
    context = snapshot.get("article_context") if isinstance(snapshot.get("article_context"), dict) else {}
    names_by_ref: dict[int, str] = {}
    for source in context.get("sources") or []:
        if not isinstance(source, dict) or source.get("ref") is None:
            continue
        name = str(source.get("name") or "").strip()
        if not name:
            continue
        try:
            names_by_ref[int(source["ref"])] = name
        except (TypeError, ValueError):
            continue
    found: list[str] = []
    for key in _CONTEXT_CLAIM_KEYS:
        for claim in context.get(key) or []:
            if not isinstance(claim, dict) or str(claim.get("id") or "") != claim_id:
                continue
            for evidence in claim.get("evidence") or []:
                if not isinstance(evidence, dict) or evidence.get("source_ref") is None:
                    continue
                try:
                    name = names_by_ref.get(int(evidence["source_ref"]))
                except (TypeError, ValueError):
                    name = None
                if name and name not in found:
                    found.append(name)
    return found


def _rewrite_contract(claim: dict[str, Any] | None, decision: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(decision, dict) and not isinstance(claim, dict):
        return None
    from app.schemas.editorial_evidence import read_evaluation_state, read_public_rendering
    from app.services.editorial_reason import public_resolution_fields

    source = decision if isinstance(decision, dict) else {}
    fields = public_resolution_fields(source)
    state = read_evaluation_state(source)
    rendering = read_public_rendering(source)
    basis = _support_basis(source, claim if isinstance(claim, dict) else None)
    claim_id = ""
    if isinstance(claim, dict):
        claim_id = _claim_id(claim) or ""
    if not claim_id:
        claim_id = str(source.get("claim_id") or "")
    return {
        "claim_id": claim_id or None,
        "status": source.get("status"),
        "evaluation_state": state.value if state is not None else None,
        "reason_code": fields.get("reason_code"),
        "verified_scope": fields.get("verified_scope"),
        "unsupported_scope": fields.get("unsupported_scope"),
        "public_rendering": rendering.model_dump() if rendering is not None else None,
        "information_origins": _information_origins(basis),
        "named_sources": [],
    }


def blocking_issues(issues: list[AuditIssue]) -> list[AuditIssue]:
    return [issue for issue in issues if issue.severity in _BLOCKING]


def merge_audit_result(
    llm_result: ArticleAuditResult | None,
    structural: list[AuditIssue] | None = None,
    *,
    article: Article | None = None,
    snapshot: dict[str, Any] | None = None,
) -> ArticleAuditResult:
    llm_issues = list(llm_result.issues) if llm_result is not None else []
    if article is not None:
        llm_issues = drop_attributed_single_as_corroborated(llm_issues, article)
    if snapshot is not None:
        llm_issues = drop_mismatched_llm_claim_links(llm_issues, snapshot)
    certainty = certainty_findings(article, snapshot) if article is not None else []
    issues = _dedupe_issues(list(structural or []) + certainty + llm_issues)
    issues = apply_headline_attribution_tolerance(issues, article, snapshot)
    blocking = blocking_issues(issues)
    passed = not blocking
    return ArticleAuditResult(passed=passed, issues=issues, editorial_passed=passed)


def _clause_is_negated(text: str, index: int) -> bool:
    window = text[max(0, index - 36) : index]
    return any(prefix in window for prefix in _NEGATION_PREFIXES)


def passage_is_attributed(text: str) -> bool:
    lowered = (text or "").casefold()
    return any(marker in lowered for marker in _ATTRIBUTION_MARKERS)


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


def _status_value(raw: Any) -> str:
    if hasattr(raw, "value"):
        return str(raw.value)
    return str(raw or "")


def _claim_id(row: dict[str, Any]) -> str | None:
    value = row.get("id") or row.get("claim_id")
    return str(value) if value else None


def _single_source_rows(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    context = snapshot.get("article_context") if isinstance(snapshot.get("article_context"), dict) else {}
    buckets: list[Any] = []
    for key in ("single_source_claims", "uncertain_claims"):
        buckets.extend(context.get(key) or [])
    buckets.extend(snapshot.get("evaluated_claims") or [])
    for row in buckets:
        if not isinstance(row, dict):
            continue
        status = _status_value(row.get("status"))
        if status not in _SINGLE_LIKE:
            continue
        claim_id = _claim_id(row) or row.get("canonical_text") or ""
        if claim_id in seen:
            continue
        seen.add(str(claim_id))
        rows.append(row)
    return rows


def article_surface_map(article: Article) -> dict[str, str]:
    """Titular, bajada y lead (primer body_block o primer párrafo). El cuerpo posterior no cuenta."""
    surfaces: dict[str, str] = {}
    headline = (article.headline or "").strip()
    if headline:
        surfaces["headline"] = headline
    summary = (article.summary or "").strip()
    if summary:
        surfaces["summary"] = summary
    lead = ""
    blocks = article.body_blocks
    if isinstance(blocks, list) and blocks:
        lead = (block_plain_text(blocks[0]) or "").strip()
    if not lead:
        parts = split_body_paragraphs(article.body or "")
        lead = parts[0].strip() if parts else ""
    if lead:
        surfaces["lead"] = lead
    return surfaces


def _article_surfaces(article: Article) -> list[str]:
    """Titular, bajada y lead: el cuerpo posterior no sana ni condena esas piezas."""
    return list(article_surface_map(article).values())


def _digits(value: str | None) -> str:
    return "".join(ch for ch in (value or "") if ch.isdigit())


def _surface_mentions_claim(surface: str, claim: dict[str, Any]) -> bool:
    compact = (surface or "").casefold().replace(" ", "").replace(".", "").replace(",", "")
    value = _digits(str(claim.get("normalized_value") or ""))
    text = str(claim.get("canonical_text") or "")
    if not value:
        value = _digits(text)
    if value and len(value) >= 4 and value in compact:
        return True
    folded_surface = (surface or "").casefold().strip().rstrip(".")
    folded_claim = text.casefold()
    if folded_surface and len(folded_surface) >= 12 and folded_surface in folded_claim:
        return True
    tokens = token_set(text) - _CLAIM_STOP
    if len(tokens) < 2:
        return False
    overlap = tokens & token_set(surface)
    needed = 2 if len(tokens) <= 4 else 3
    return len(overlap) >= needed


def drop_attributed_single_as_corroborated(issues: list[AuditIssue], article: Article) -> list[AuditIssue]:
    from app.services.surface_validation import assertions_are_attributed

    _ = article
    kept: list[AuditIssue] = []
    for issue in issues:
        if issue.reason != AuditIssueReason.SINGLE_AS_CORROBORATED:
            kept.append(issue)
            continue
        fragment = (issue.text or "").strip()
        if fragment and assertions_are_attributed(fragment):
            continue
        kept.append(issue)
    return kept


_SURFACE_LABELS = {"headline", "summary", "lead", "bajada"}
_DIGIT_RE = re.compile(r"\b\d{2,}\b")
_CULPABILITY_RE = re.compile(
    r"\b(asesin[oó]s?|asesinada|asesinado|culpables?|femicidas?|homicidas?)\b",
    re.IGNORECASE,
)
_HEADLINE_BOOSTERS = (
    "confirmado",
    "comprobado",
    "verificado",
    "fuentes independientes",
    "corroborad",
)
_HEADLINE_OMISSION_REASONS = {
    AuditIssueReason.SINGLE_AS_CORROBORATED,
    AuditIssueReason.SURFACE_ATTRIBUTION,
    AuditIssueReason.SURFACE_CATEGORICAL,
}
HEADLINE_TOLERANCE_NOTE = (
    "Omisión de atribución solo en el titular, tolerada por la política editorial. "
    "La bajada o el primer párrafo atribuyen la misma proposición SINGLE_SOURCE. "
    "No cambia el status ni los permisos de evidencia."
)


def _snapshot_claim_index(snapshot: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, str]]:
    from app.services.surface_validation import _decisions, _snapshot_claims

    claims = {_claim_id(row): row for row in _snapshot_claims(snapshot) if _claim_id(row)}
    decisions = _decisions(snapshot)
    context = snapshot.get("article_context") if isinstance(snapshot.get("article_context"), dict) else {}
    raw_refs = context.get("claim_refs") if isinstance(context.get("claim_refs"), dict) else {}
    refs = {str(key): str(value) for key, value in raw_refs.items()}
    return claims, decisions, refs


def resolve_issue_claim(
    issue: AuditIssue,
    snapshot: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str | None]:
    """Resuelve claim_id o claim_ref. None, None, token significa referencia no resoluble."""
    if snapshot is None:
        return None, None, None
    claims, decisions, refs = _snapshot_claim_index(snapshot)
    cid = str(issue.claim_id) if issue.claim_id else ""
    ref = str(issue.claim_ref or "").strip()
    if cid and (cid in claims or cid in decisions):
        return claims.get(cid), decisions.get(cid), None
    if ref.casefold() in _SURFACE_LABELS:
        return None, None, None
    mapped = refs.get(ref) if ref else ""
    if mapped and (mapped in claims or mapped in decisions):
        return claims.get(mapped), decisions.get(mapped), None
    if ref and (ref in claims or ref in decisions):
        return claims.get(ref), decisions.get(ref), None
    token = cid or ref
    if token:
        return None, None, token
    return None, None, None


def _digit_numbers(text: str) -> set[str]:
    return set(_DIGIT_RE.findall(text or ""))


def _negation_mismatch(surface: str, claim: dict[str, Any]) -> bool:
    from app.services.surface_validation import _claim_text, _content_tokens

    claim_text = _claim_text(claim).casefold()
    folded = (surface or "").casefold()
    claim_neg = any(prefix in claim_text for prefix in _NEGATION_PREFIXES)
    surface_neg = any(prefix in folded for prefix in _NEGATION_PREFIXES)
    if claim_neg == surface_neg:
        return False
    return bool(_content_tokens(claim_text) & _content_tokens(folded))


def _number_mismatch(surface: str, claim: dict[str, Any]) -> bool:
    from app.services.surface_validation import _claim_text, _content_tokens

    claim_text = _claim_text(claim)
    claim_nums = _digit_numbers(claim_text)
    surface_nums = _digit_numbers(surface)
    if not claim_nums or not surface_nums:
        return False
    if not (claim_nums - surface_nums and surface_nums - claim_nums):
        return False
    return bool(_content_tokens(claim_text) & _content_tokens(surface))


def drop_mismatched_llm_claim_links(issues: list[AuditIssue], snapshot: dict[str, Any] | None) -> list[AuditIssue]:
    """Descarta un issue cuyo claim resuelto no es la proposición del fragmento.

    Conserva una diferencia de cifra del mismo hecho y las referencias que no se pueden resolver.
    headline/summary/lead no son IDs.
    """
    if snapshot is None:
        return issues
    from app.services.surface_validation import asserted_link

    kept: list[AuditIssue] = []
    for issue in issues:
        claim, decision, unresolved = resolve_issue_claim(issue, snapshot)
        if unresolved or claim is None:
            kept.append(issue)
            continue
        fragment = issue.text or ""
        kind = asserted_link(fragment, claim, decision)
        same_fact_shift = issue.reason in {
            AuditIssueReason.SEMANTIC_SHIFT,
            AuditIssueReason.PARTIAL_AS_TOTAL,
        }
        if (
            kind == "equivalent"
            or same_fact_shift
            or _number_mismatch(fragment, claim)
            or _negation_mismatch(fragment, claim)
        ):
            kept.append(issue)
    return kept


def certainty_findings(article: Article | None, snapshot: dict[str, Any] | None) -> list[AuditIssue]:
    if article is None or snapshot is None:
        return []
    from app.services.surface_validation import _assertion_attributed, _claim_text, asserted_link

    claims = _single_source_rows(snapshot)
    if not claims:
        return []
    _, decisions, _refs = _snapshot_claim_index(snapshot)
    issues: list[AuditIssue] = []
    seen: set[tuple[str, str]] = set()
    for surface_name, surface in article_surface_map(article).items():
        for claim in claims:
            cid = _claim_id(claim) or ""
            decision = decisions.get(cid)
            if asserted_link(surface, claim, decision) != "equivalent":
                continue
            if _assertion_attributed(surface, _claim_text(claim)):
                continue
            key = (surface_name, cid or _claim_text(claim))
            if key in seen:
                continue
            seen.add(key)
            issues.append(
                _issue(
                    issue_type=AuditIssueType.UNSUPPORTED_CLAIM,
                    reason=AuditIssueReason.SINGLE_AS_CORROBORATED,
                    text=surface,
                    explanation=(
                        "Proposición SINGLE_SOURCE presentada como hecho categórico, sin atribución explícita."
                    ),
                    action=AuditIssueAction.ATTRIBUTE,
                    claim_id=cid or None,
                    claim_ref=surface_name,
                )
            )
    return issues


def _issue_targets_headline(issue: AuditIssue, headline: str) -> bool:
    if issue.reason not in _HEADLINE_OMISSION_REASONS:
        return False
    if str(issue.claim_ref or "").casefold() == "headline":
        return True
    text = " ".join((issue.text or "").split())
    head = " ".join((headline or "").split())
    if not text or not head:
        return False
    return text == head or text in head or head in text


def _attributed_surface_has_numbers(surface: str, numbers: set[str]) -> bool:
    from app.services.surface_validation import _assertion_spans, _sentence_spans

    if not numbers or not numbers <= _digit_numbers(surface):
        return False
    folded = surface.casefold()
    covered: set[str] = set()
    for sent_start, sent_end in _sentence_spans(folded):
        sentence = folded[sent_start:sent_end]
        for ass_start, ass_end in _assertion_spans(sentence):
            clause = sentence[ass_start:ass_end]
            if not any(marker in clause for marker in _ATTRIBUTION_MARKERS):
                continue
            covered |= _digit_numbers(clause) & numbers
    return numbers <= covered


def headline_omission_is_tolerated(issue: AuditIssue, article: Article, snapshot: dict[str, Any] | None) -> bool:
    headline = article.headline or ""
    if snapshot is None or not _issue_targets_headline(issue, headline):
        return False
    if _CULPABILITY_RE.search(headline) or any(token in headline.casefold() for token in _HEADLINE_BOOSTERS):
        return False
    numbers = _digit_numbers(headline)
    if not numbers:
        return False
    claim, decision, unresolved = resolve_issue_claim(issue, snapshot)
    if unresolved or not isinstance(decision, dict):
        return False
    status = _status_value(decision.get("status") or (claim or {}).get("status"))
    if status != "SINGLE_SOURCE":
        return False
    if str(decision.get("evaluation_state") or "").casefold() != "complete":
        return False
    basis = decision.get("support_basis") if isinstance(decision.get("support_basis"), dict) else None
    claim_basis = (claim or {}).get("support_basis") if isinstance((claim or {}).get("support_basis"), dict) else None
    support = basis or claim_basis
    if not support and not str(decision.get("verified_scope") or "").strip():
        return False
    claim_text = " ".join(
        str(part or "")
        for part in (
            (claim or {}).get("canonical_text"),
            decision.get("verified_scope"),
        )
    )
    if not numbers <= _digit_numbers(claim_text):
        return False
    surfaces = article_surface_map(article)
    attributed = _attributed_surface_has_numbers(surfaces.get("summary") or "", numbers) or _attributed_surface_has_numbers(
        surfaces.get("lead") or "", numbers
    )
    return attributed


def normalized_structural_issues(
    snapshot: dict[str, Any] | None,
    article: Article | None,
) -> list[AuditIssue]:
    """Los mismos estructurales que Audit, ya normalizados.

    Publish revalida integridad, cobertura y correspondencia. La excepción de
    omisión en el titular usa esta función, no una regla aparte.
    """
    if article is None:
        return []
    return apply_headline_attribution_tolerance(
        structural_findings(snapshot, article),
        article,
        snapshot if isinstance(snapshot, dict) else None,
    )


def apply_headline_attribution_tolerance(
    issues: list[AuditIssue],
    article: Article | None,
    snapshot: dict[str, Any] | None,
) -> list[AuditIssue]:
    if article is None:
        return issues
    out: list[AuditIssue] = []
    for issue in issues:
        if issue.severity not in _BLOCKING or not headline_omission_is_tolerated(issue, article, snapshot):
            out.append(issue)
            continue
        out.append(
            issue.model_copy(
                update={
                    "severity": AuditIssueSeverity.LOW,
                    "action": AuditIssueAction.ATTRIBUTE,
                    "suggested_fix": None,
                    "explanation": f"{HEADLINE_TOLERANCE_NOTE} {issue.explanation or ''}".strip(),
                }
            )
        )
    return out


def _dedupe_issues(issues: list[AuditIssue]) -> list[AuditIssue]:
    seen: set[tuple[Any, ...]] = set()
    out: list[AuditIssue] = []
    for issue in issues:
        key = (
            issue.reason,
            issue.type,
            (issue.text or "").strip()[:240],
            issue.claim_id or "",
            issue.claim_ref or "",
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(issue)
    return out
