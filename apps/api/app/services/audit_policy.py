from __future__ import annotations

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


def structural_blocks_rewrite(issues: list[AuditIssue]) -> bool:
    return any(issue.reason in _STRUCTURAL_REASONS and issue.severity in _BLOCKING for issue in issues)


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
    kept: list[AuditIssue] = []
    surfaces = _article_surfaces(article)
    for issue in issues:
        if issue.reason != AuditIssueReason.SINGLE_AS_CORROBORATED:
            kept.append(issue)
            continue
        fragment = (issue.text or "").strip()
        if passage_is_attributed(fragment):
            continue
        attributed_surface = False
        for surface in surfaces:
            if fragment and fragment in surface and passage_is_attributed(surface):
                attributed_surface = True
                break
            if surface.strip() == fragment and passage_is_attributed(surface):
                attributed_surface = True
                break
        if not attributed_surface:
            kept.append(issue)
    return kept


def drop_mismatched_llm_claim_links(issues: list[AuditIssue], snapshot: dict[str, Any] | None) -> list[AuditIssue]:
    """Descarta findings del modelo que citan un claim de otro hecho, tiempo o alcance."""
    if snapshot is None:
        return issues
    from app.services.surface_validation import _decisions, _snapshot_claims, classify_link

    claims = {_claim_id(row): row for row in _snapshot_claims(snapshot) if _claim_id(row)}
    decisions = _decisions(snapshot)
    kept: list[AuditIssue] = []
    for issue in issues:
        cid = issue.claim_id
        if not cid:
            kept.append(issue)
            continue
        claim = claims.get(str(cid))
        if claim is None:
            kept.append(issue)
            continue
        kind = classify_link(issue.text or "", claim, decisions.get(str(cid)))
        if kind in {"equivalent", "partial"}:
            kept.append(issue)
            continue
    return kept


def certainty_findings(article: Article | None, snapshot: dict[str, Any] | None) -> list[AuditIssue]:
    if article is None or snapshot is None:
        return []
    claims = _single_source_rows(snapshot)
    if not claims:
        return []
    issues: list[AuditIssue] = []
    for surface in _article_surfaces(article):
        if passage_is_attributed(surface):
            continue
        from app.services.surface_validation import classify_link

        matched = next((claim for claim in claims if classify_link(surface, claim) == "equivalent"), None)
        if matched is None:
            continue
        issues.append(
            _issue(
                issue_type=AuditIssueType.UNSUPPORTED_CLAIM,
                reason=AuditIssueReason.SINGLE_AS_CORROBORATED,
                text=surface,
                explanation=(
                    "Proposición SINGLE_SOURCE presentada como hecho categórico, sin atribución explícita."
                ),
                action=AuditIssueAction.ATTRIBUTE,
                claim_id=_claim_id(matched),
            )
        )
    return issues


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
