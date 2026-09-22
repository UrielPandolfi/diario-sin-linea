from __future__ import annotations

import re
from typing import Any, Literal

from app.core.text import token_set
from app.schemas.auditing import (
    AuditIssue,
    AuditIssueAction,
    AuditIssueReason,
    AuditIssueSeverity,
    AuditIssueType,
)
from app.schemas.editorial_evidence import (
    CoverageMatch,
    EvaluationState,
    PublicRendering,
    decision_looks_like_skip,
    read_evaluation_state,
    read_public_rendering,
)
from app.services.audit_policy import (
    _ATTRIBUTION_MARKERS,
    _CLAIM_STOP,
    _PLURAL_PHRASES,
    _clause_is_negated,
    _claim_id,
    _surface_mentions_claim,
    article_surface_map,
)
from app.services.claim_coverage import _act_bucket, propositions_equivalent
from app.services.evidence_snapshot import snapshot_context_claims

_INDEPENDENT_PHRASES = _PLURAL_PHRASES + (
    "fuentes independientes confirmaron",
    "confirmado de forma independiente",
    "corroboración independiente",
    "corroboracion independiente",
    "orígenes independientes",
    "origenes independientes",
    "confirmado por fuentes independientes",
)

_MODAL_PHRASES = (
    "podría ",
    "podria ",
    "podrían ",
    "podrian ",
    "es posible que",
    "se estima que",
    "se prevé que",
    "se preve que",
    "en previsión",
    "en prevision",
    "no se confirmó que",
    "no se confirmo que",
    "no está confirmado que",
    "no esta confirmado que",
)

_DISPUTE_PHRASES = (
    "está en disputa",
    "esta en disputa",
    "en disputa",
    "en conflicto",
    "versiones enfrentadas",
    "se contradicen",
    "no hay consenso",
    "fuentes discrepan",
    "está cuestionad",
    "esta cuestionad",
)

_CONTRADICTION_PHRASES = (
    "una evidencia contradice",
    "la evidencia contradice",
    "contradice que",
    "desmiente que",
    "queda desmentid",
    "fue desmentid",
)

LinkKind = Literal["equivalent", "partial", "mention", "none"]

_DISTINCTIVE_NUM = re.compile(r"(?<!\d)(?:\d{1,3}(?:[.\s]\d{3})+|\d{3,})(?!\d)")
_ASSERTION_SPLITTERS = (
    " mientras que",
    " en tanto que",
    " aunque ",
    " aunque,",
    " pero ",
    " pero,",
    " sino que",
    " no obstante",
    " sin embargo",
    " por otro lado",
)


def _issue(
    *,
    reason: AuditIssueReason,
    surface: str,
    text: str,
    explanation: str,
    claim_id: str | None = None,
    severity: AuditIssueSeverity = AuditIssueSeverity.HIGH,
    issue_type: AuditIssueType = AuditIssueType.UNSUPPORTED_CLAIM,
) -> AuditIssue:
    fragment = " ".join((text or "").split())
    if len(fragment) > 240:
        fragment = fragment[:237] + "..."
    return AuditIssue(
        type=issue_type,
        severity=severity,
        text=fragment,
        explanation=explanation,
        suggested_fix=None,
        reason=reason,
        action=AuditIssueAction.REVIEW,
        claim_id=claim_id,
        claim_ref=surface,
    )


def _importance(row: dict[str, Any]) -> str:
    raw = row.get("importance")
    if hasattr(raw, "value"):
        return str(raw.value).upper()
    return str(raw or "MEDIUM").upper()


def _claim_text(row: dict[str, Any]) -> str:
    return str(row.get("canonical_text") or "")


def _is_utterance_claim(claim: dict[str, Any], decision: dict[str, Any] | None) -> bool:
    if _utterance_role_or_type(claim, decision):
        return True
    return _act_bucket(_claim_text(claim)) == "utterance"


def _utterance_role_or_type(claim: dict[str, Any], decision: dict[str, Any] | None) -> bool:
    role = ""
    if isinstance(decision, dict):
        role = str(decision.get("proposition_role") or "")
    if not role:
        role = str(claim.get("proposition_role") or "")
    if role == "utterance":
        return True
    return str(claim.get("claim_type") or "") == "declaracion"


def _snapshot_claims(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for row in snapshot.get("evaluated_claims") or []:
        if not isinstance(row, dict):
            continue
        cid = _claim_id(row)
        if cid:
            by_id[cid] = dict(row)
    for cid, row in snapshot_context_claims(snapshot).items():
        merged = {**by_id.get(cid, {}), **row, "id": cid}
        by_id[cid] = merged
    return list(by_id.values())


def _decisions(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = snapshot.get("decision_by_claim_id")
    if isinstance(raw, dict) and raw:
        return {str(key): value for key, value in raw.items() if isinstance(value, dict)}
    context = snapshot.get("article_context") if isinstance(snapshot.get("article_context"), dict) else {}
    verification = context.get("verification") if isinstance(context.get("verification"), dict) else {}
    nested = verification.get("decision_by_claim_id")
    if isinstance(nested, dict):
        return {str(key): value for key, value in nested.items() if isinstance(value, dict)}
    return {}


def _material_claims(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    high = [row for row in claims if _importance(row) == "HIGH"]
    if high:
        return high
    return [row for row in claims if _importance(row) != "LOW"]


def _content_tokens(text: str) -> set[str]:
    return token_set(text) - _CLAIM_STOP


def _same_fact_texts(left: str, right: str) -> bool:
    """Misma proposición, no solo overlap temático. C5 no cambia este umbral de C8."""
    if propositions_equivalent(left, right) is not CoverageMatch.EQUIVALENT:
        return False
    left_toks = _content_tokens(left)
    right_toks = _content_tokens(right)
    if not left_toks or not right_toks:
        return False
    return len(left_toks & right_toks) / len(left_toks | right_toks) >= 0.55


def _distinctive_numbers(text: str) -> set[str]:
    found: set[str] = set()
    for raw in _DISTINCTIVE_NUM.findall(text or ""):
        digits = "".join(ch for ch in raw if ch.isdigit())
        if len(digits) >= 3:
            found.add(digits.lstrip("0") or "0")
    return found


def _c5_keeps_equivalent(surface: str, claim_text: str) -> bool:
    """C5 only. Does not change C8 coverage matching.

    Drop a lax EQUIVALENT when the claim's distinctive numbers are absent from the
    surface, or when neither Jaccard nor claim-token coverage is strong enough.
    Extra tokens on the surface (lugar, marco) do not disqualify a covered claim.
    """
    claim_nums = _distinctive_numbers(claim_text)
    surface_nums = _distinctive_numbers(surface)
    if claim_nums - surface_nums:
        return False
    claim_toks = _content_tokens(claim_text)
    surface_toks = _content_tokens(surface)
    if not claim_toks or not surface_toks:
        return False
    shared = claim_toks & surface_toks
    jaccard = len(shared) / len(claim_toks | surface_toks)
    coverage = len(shared) / len(claim_toks)
    return jaccard >= 0.35 or coverage >= 0.5


def classify_link(surface: str, claim: dict[str, Any], decision: dict[str, Any] | None = None) -> LinkKind:
    text = _claim_text(claim)
    if not (surface or "").strip() or not text.strip():
        return "none"
    verified = str((decision or {}).get("verified_scope") or "").strip()
    if verified and propositions_equivalent(surface, verified) is CoverageMatch.EQUIVALENT:
        if _c5_keeps_equivalent(surface, verified):
            return "equivalent"
        return "partial"
    match = propositions_equivalent(surface, text)
    if match is CoverageMatch.EQUIVALENT:
        if _c5_keeps_equivalent(surface, text):
            return "equivalent"
        return "partial"
    if match is CoverageMatch.PARTIAL:
        return "partial"
    if _surface_mentions_claim(surface, claim):
        return "mention"
    return "none"


def _sentence_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    start = 0
    for match in re.finditer(r"\.(?:\s+|$)", text):
        pos = match.start()
        prev = text[pos - 1] if pos > 0 else ""
        nxt = text[pos + 1] if pos + 1 < len(text) else ""
        if prev.isdigit() and nxt.isdigit():
            continue
        spans.append((start, pos + 1))
        start = match.end()
    if start < len(text):
        spans.append((start, len(text)))
    return spans or [(0, len(text))]


def _assertion_spans(sentence: str) -> list[tuple[int, int]]:
    folded = sentence
    cuts = {0, len(sentence)}
    for marker in _ASSERTION_SPLITTERS:
        start = 0
        while True:
            pos = folded.find(marker, start)
            if pos < 0:
                break
            cuts.add(pos)
            start = pos + len(marker)
    ordered = sorted(cuts)
    return [(ordered[i], ordered[i + 1]) for i in range(len(ordered) - 1)]


def _span_containing(index: int, spans: list[tuple[int, int]], length: int) -> tuple[int, int]:
    for start, end in spans:
        if start <= index < end:
            return start, end
    return 0, length


def _assertion_attributed(surface: str, claim_text: str) -> bool:
    folded = (surface or "").casefold()
    if not folded.strip():
        return False
    tokens = [tok for tok in sorted(_content_tokens(claim_text), key=len, reverse=True) if len(tok) >= 4]
    index = -1
    for tok in tokens[:4]:
        pos = folded.find(tok)
        if pos >= 0:
            index = pos
            break
    if index < 0:
        return False
    sent_start, sent_end = _span_containing(index, _sentence_spans(folded), len(folded))
    sentence = folded[sent_start:sent_end]
    local = index - sent_start
    ass_start, ass_end = _span_containing(local, _assertion_spans(sentence), len(sentence))
    assertion = sentence[ass_start:ass_end]
    return any(marker in assertion for marker in _ATTRIBUTION_MARKERS)


def _is_modal(surface: str) -> bool:
    folded = (surface or "").casefold()
    return any(phrase in folded for phrase in _MODAL_PHRASES)


def _reports_dispute(surface: str) -> bool:
    folded = (surface or "").casefold()
    return any(phrase in folded for phrase in _DISPUTE_PHRASES)


def _reports_contradiction(surface: str) -> bool:
    folded = (surface or "").casefold()
    return any(phrase in folded for phrase in _CONTRADICTION_PHRASES)


def signals_independent_confirmation_language(text: str) -> bool:
    lowered = (text or "").casefold()
    for phrase in _INDEPENDENT_PHRASES:
        index = lowered.find(phrase)
        if index == -1:
            continue
        if _clause_is_negated(lowered, index):
            continue
        return True
    return False


def _usable_rendering(decision: dict[str, Any] | None) -> tuple[PublicRendering | None, str]:
    state = read_evaluation_state(decision)
    if state is EvaluationState.SKIPPED or decision_looks_like_skip(decision):
        return None, "incomplete"
    rendering = read_public_rendering(decision)
    if state is EvaluationState.COMPLETE:
        if rendering is None:
            return None, "incomplete"
        return rendering, "ok"
    return None, "incomplete"


def _asserts_as_world_fact(surface: str, claim: dict[str, Any], decision: dict[str, Any] | None) -> bool:
    if _reports_dispute(surface) or _reports_contradiction(surface) or _is_modal(surface):
        return False
    utterance_claim = _is_utterance_claim(claim, decision)
    utterance_surface = _act_bucket(surface) == "utterance"
    if utterance_claim and not utterance_surface:
        return True
    if not utterance_claim and utterance_surface:
        return False
    if _assertion_attributed(surface, _claim_text(claim)):
        return False
    return True


def _headline_nucleus(headline: str) -> str:
    text = (headline or "").strip()
    folded = text.casefold()
    for marker in ("según ", "segun ", "de acuerdo con"):
        if folded.startswith(marker):
            comma = text.find(",")
            if 0 <= comma < len(text) - 1:
                return text[comma + 1 :].strip()
            break
    return text


def _surface_rule_findings(
    *,
    name: str,
    text: str,
    claims: list[dict[str, Any]],
    decisions: dict[str, dict[str, Any]],
) -> list[AuditIssue]:
    issues: list[AuditIssue] = []
    equivalent: list[tuple[dict[str, Any], dict[str, Any] | None, PublicRendering, str]] = []
    weak = False
    for claim in claims:
        cid = _claim_id(claim)
        decision = decisions.get(cid) if cid else None
        kind = classify_link(text, claim, decision)
        if kind in {"partial", "mention"}:
            weak = True
            issues.append(
                _issue(
                    reason=AuditIssueReason.SURFACE_INDETERMINATE,
                    surface=name,
                    text=text,
                    explanation=(
                        f"El {name} coincide en tokens o parcialmente con un claim, "
                        "pero no hay equivalencia proposicional suficiente para validar ni para bloquear."
                    ),
                    claim_id=cid,
                    severity=AuditIssueSeverity.LOW,
                    issue_type=AuditIssueType.CLARITY,
                )
            )
            continue
        if kind != "equivalent":
            continue
        rendering, mode = _usable_rendering(decision)
        if mode == "incomplete" or rendering is None:
            issues.append(
                _issue(
                    reason=AuditIssueReason.SURFACE_CONTRACT_INCOMPLETE,
                    surface=name,
                    text=text,
                    explanation=(
                        f"El {name} se vincula a un claim del snapshot de esta versión, "
                        "pero no hay public_rendering usable. No se inventan permisos ni se consulta Verification live."
                    ),
                    claim_id=cid,
                )
            )
            continue
        equivalent.append((claim, decision, rendering, mode))

    conflict_ids: set[str] = set()

    def _flag_conflict(claim_a, decision_a, rendering_a, claim_b, decision_b, rendering_b) -> None:
        statuses = {(decision_a or {}).get("status"), (decision_b or {}).get("status")}
        statuses.discard(None)
        statuses.discard("")
        if (
            len(statuses) <= 1
            and rendering_a.categorical_allowed == rendering_b.categorical_allowed
            and rendering_a.attribution_required == rendering_b.attribution_required
        ):
            return
        cid = _claim_id(claim_a)
        issues.append(
            _issue(
                reason=AuditIssueReason.SURFACE_CONTRACT_INCOMPLETE,
                surface=name,
                text=text,
                explanation=(
                    f"El {name} equivale a claims del snapshot con contratos incompatibles "
                    "para el mismo hecho. No se elige el permiso más favorable ni el más restrictivo."
                ),
                claim_id=cid,
            )
        )
        if cid:
            conflict_ids.add(cid)
        other = _claim_id(claim_b)
        if other:
            conflict_ids.add(other)

    for index, (claim_a, decision_a, rendering_a, _mode_a) in enumerate(equivalent):
        for claim_b, decision_b, rendering_b, _mode_b in equivalent[index + 1 :]:
            if _same_fact_texts(_claim_text(claim_a), _claim_text(claim_b)):
                _flag_conflict(claim_a, decision_a, rendering_a, claim_b, decision_b, rendering_b)

    matched_ids = {_claim_id(row[0]) for row in equivalent if _claim_id(row[0])}
    for claim in claims:
        cid = _claim_id(claim)
        if not cid or cid in matched_ids:
            continue
        decision = decisions.get(cid)
        rendering, mode = _usable_rendering(decision)
        if mode == "incomplete" or rendering is None:
            continue
        for matched, decision_m, rendering_m, _mode_m in equivalent:
            if not _same_fact_texts(_claim_text(matched), _claim_text(claim)):
                continue
            _flag_conflict(matched, decision_m, rendering_m, claim, decision, rendering)
            break

    if not equivalent and not weak:
        return issues

    has_fact_equivalent = any(
        not _utterance_role_or_type(claim, decision) for claim, decision, _rendering, _mode in equivalent
    )
    # Si hay un hecho equivalente, el utterance hermano (p. ej. recovery de «reconoció»)
    # no aporta permisos ni veta la formulación: se valida contra el contrato del hecho.
    # Una caracterización cotizada no es ese hermano y se examina aparte.
    targets = [
        row
        for row in equivalent
        if _claim_id(row[0]) not in conflict_ids
        and (not has_fact_equivalent or not _utterance_role_or_type(row[0], row[1]))
    ]

    for claim, decision, rendering, _mode in targets:
        cid = _claim_id(claim)
        attributed = _assertion_attributed(text, _claim_text(claim))
        needs_attribution = bool(rendering.attribution_required)
        if name == "headline" and rendering.headline_unattributed_allowed is False:
            needs_attribution = True
        skip_assertion = _reports_dispute(text) or _reports_contradiction(text)
        if needs_attribution and not attributed and not skip_assertion:
            issues.append(
                _issue(
                    reason=AuditIssueReason.SURFACE_ATTRIBUTION,
                    surface=name,
                    text=text,
                    explanation=(
                        f"El {name} usa un claim que exige atribución de la afirmación y su emisor o fuente. "
                        "Un 'según' en otra superficie o en otra cláusula no alcanza."
                    ),
                    claim_id=cid,
                    issue_type=AuditIssueType.ATTRIBUTION,
                )
            )
        utterance_surface = _act_bucket(text) == "utterance"
        content_as_fact = (
            _is_utterance_claim(claim, decision)
            and not utterance_surface
            and not skip_assertion
            and not _is_modal(text)
            and not has_fact_equivalent
        )
        flag_categorical = content_as_fact or (
            rendering.categorical_allowed is False and _asserts_as_world_fact(text, claim, decision)
        )
        if flag_categorical:
            issues.append(
                _issue(
                    reason=AuditIssueReason.SURFACE_CATEGORICAL,
                    surface=name,
                    text=text,
                    explanation=(
                        f"El {name} afirma de forma categórica una proposición cuyo contrato solo autoriza "
                        "atribución, modalidad o un alcance menor. Acreditar un dicho no acredita su contenido."
                    ),
                    claim_id=cid,
                )
            )
        if signals_independent_confirmation_language(text) and (
            rendering.independent_confirmation_language_allowed is False
        ):
            issues.append(
                _issue(
                    reason=AuditIssueReason.SURFACE_INDEPENDENT_LANGUAGE,
                    surface=name,
                    text=text,
                    explanation=(
                        f"El {name} usa lenguaje de corroboración independiente que el contrato del claim no permite. "
                        "Informar que varios medios publicaron no equivale a esa fórmula."
                    ),
                    claim_id=cid,
                    issue_type=AuditIssueType.INFERENCE,
                )
            )
    return issues


def _coverage_findings(headline: str, claims: list[dict[str, Any]], decisions: dict[str, dict[str, Any]]) -> list[AuditIssue]:
    if not (headline or "").strip():
        return []
    nucleus = _headline_nucleus(headline)
    if len(_content_tokens(nucleus)) < 2:
        return [
            _issue(
                reason=AuditIssueReason.SURFACE_INDETERMINATE,
                surface="headline",
                text=headline,
                explanation=(
                    "No hay núcleo informativo con tokens suficientes para comprobar cobertura "
                    "con matching determinista."
                ),
                severity=AuditIssueSeverity.LOW,
                issue_type=AuditIssueType.CLARITY,
            )
        ]
    material = _material_claims(claims)
    accessory = [row for row in claims if row not in material]
    eq_material = [
        row for row in material if classify_link(nucleus, row, decisions.get(_claim_id(row) or "")) == "equivalent"
    ]
    if eq_material:
        return []
    eq_accessory = [
        row for row in accessory if classify_link(nucleus, row, decisions.get(_claim_id(row) or "")) == "equivalent"
    ]
    weak_material = [
        row
        for row in material
        if classify_link(nucleus, row, decisions.get(_claim_id(row) or "")) in {"partial", "mention"}
        or bool(_content_tokens(nucleus) & _content_tokens(_claim_text(row)))
    ]
    if eq_accessory:
        return [
            _issue(
                reason=AuditIssueReason.HEADLINE_UNCOVERED,
                surface="headline",
                text=headline,
                explanation=(
                    "El núcleo del titular no tiene un claim material equivalente en el snapshot de esta versión. "
                    "Un claim accesorio no cubre ese núcleo."
                ),
                claim_id=_claim_id(eq_accessory[0]),
                issue_type=AuditIssueType.UNMAPPED_MATERIAL_CLAIM,
            )
        ]
    if weak_material:
        return [
            _issue(
                reason=AuditIssueReason.SURFACE_INDETERMINATE,
                surface="headline",
                text=headline,
                explanation=(
                    "El titular comparte palabras o un vínculo parcial con un claim material, "
                    "pero no hay equivalencia suficiente para dar cobertura ni para declarar un vacío identificable."
                ),
                claim_id=_claim_id(weak_material[0]),
                severity=AuditIssueSeverity.LOW,
                issue_type=AuditIssueType.CLARITY,
            )
        ]
    return [
        _issue(
            reason=AuditIssueReason.HEADLINE_UNCOVERED,
            surface="headline",
            text=headline,
            explanation=(
                "El núcleo informativo del titular no se vincula con ningún claim material del snapshot "
                "de esta versión."
            ),
            issue_type=AuditIssueType.UNMAPPED_MATERIAL_CLAIM,
        )
    ]


def surface_validation_findings(snapshot: dict[str, Any] | None, article: Any) -> list[AuditIssue]:
    if snapshot is None or article is None:
        return []
    claims = _snapshot_claims(snapshot)
    decisions = _decisions(snapshot)
    surfaces = article_surface_map(article)
    issues: list[AuditIssue] = []
    for name, text in surfaces.items():
        issues.extend(_surface_rule_findings(name=name, text=text, claims=claims, decisions=decisions))
    headline = surfaces.get("headline", "")
    issues.extend(_coverage_findings(headline, claims, decisions))
    return issues
