from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.domain.enums import ClaimStatus, EvidenceType
from app.schemas.editorial_evidence import (
    Demotion,
    PropositionRole,
    ReasonCode,
    StatementEvidenceClass,
    SupportKind,
    evaluation_is_complete,
    read_reason_code,
)

@dataclass(frozen=True)
class ReasonContext:
    status: str
    demotion: Demotion = Demotion.NONE
    known_independent: int = 0
    unknown_groups: int = 0
    authoritative_independent: int = 0
    documents_supporting: int = 0
    documents_qualifying: int = 0
    statement_evidence_class: StatementEvidenceClass | None = None
    support_kind: SupportKind | None = None
    role: PropositionRole | None = None
    primary_access: str | None = None
    rejected_disproof: bool = False


def _enum_value(value: Any) -> str:
    if value is None:
        return ""
    return str(value.value) if hasattr(value, "value") else str(value)


def _demotion(value: Any) -> Demotion:
    if isinstance(value, Demotion):
        return value
    try:
        return Demotion(str(value or Demotion.NONE.value))
    except ValueError:
        return Demotion.NONE


def _kind(value: Any) -> SupportKind | None:
    if value is None or value == "":
        return None
    if isinstance(value, SupportKind):
        return value
    try:
        return SupportKind(str(value))
    except ValueError:
        return None


def _role(value: Any) -> PropositionRole | None:
    if value is None or value == "":
        return None
    if isinstance(value, PropositionRole):
        return value
    try:
        return PropositionRole(str(value))
    except ValueError:
        return None


def _statement_class(value: Any) -> StatementEvidenceClass | None:
    if value is None or value == "":
        return None
    if isinstance(value, StatementEvidenceClass):
        return value
    try:
        return StatementEvidenceClass(str(value))
    except ValueError:
        return None


def reason_code_for(
    *,
    status: str,
    demotion: Demotion | str = Demotion.NONE,
    known_independent: int = 0,
    unknown_groups: int = 0,
    authoritative_independent: int = 0,
    documents_supporting: int = 0,
    documents_qualifying: int = 0,
    statement_evidence_class: StatementEvidenceClass | str | None = None,
    support_kind: SupportKind | str | None = None,
    role: PropositionRole | str | None = None,
    primary_access: str | None = None,
    rejected_disproof: bool = False,
) -> ReasonCode:
    """Map already-decided structured outcomes. Does not re-run gates.

    CONFLICTING / DISPROVEN codes describe post-gate ClaimStatus. They do not
    assert comparability of two raw figures. rejected_disproof is the current
    path where a requested DISPROVEN failed valid_contradiction.
    """
    status_value = _enum_value(status) or str(status)
    demotion_value = _demotion(demotion)
    kind = _kind(support_kind)
    role_value = _role(role)
    statement = _statement_class(statement_evidence_class)
    if rejected_disproof:
        return ReasonCode.CONTRADICTION_NOT_COMPARABLE
    if status_value == ClaimStatus.DISPROVEN.value:
        return ReasonCode.COMPARABLE_DISPROOF
    if status_value == ClaimStatus.CONFLICTING.value:
        return ReasonCode.CONFLICTING_COMPARABLE_EVIDENCE
    if demotion_value == Demotion.MIXED_CLAIM_NO_EXCEPTION:
        return ReasonCode.MIXED_CLAIM_NO_EXCEPTION
    if demotion_value == Demotion.MISSING_AUTHENTIC_PRIMARY:
        return ReasonCode.MISSING_AUTHENTIC_PRIMARY
    if demotion_value == Demotion.MISSING_DOCUMENTARY_PRIMARY:
        return ReasonCode.MISSING_DOCUMENTARY_PRIMARY
    if demotion_value == Demotion.UNPROVEN_INDEPENDENCE:
        return ReasonCode.INDEPENDENCE_NOT_ESTABLISHED
    if demotion_value == Demotion.INSUFFICIENT_INDEPENDENCE:
        return ReasonCode.SINGLE_KNOWN_ORIGIN
    if demotion_value == Demotion.PARTIAL_SUPPORT or (
        int(documents_qualifying or 0) > 0 and int(documents_supporting or 0) == 0
    ):
        return ReasonCode.PARTIAL_SUPPORT
    if statement == StatementEvidenceClass.AUTHENTIC_PRIMARY or (
        role_value == PropositionRole.UTTERANCE and kind == SupportKind.PRIMARY_SOURCE
    ):
        return ReasonCode.PRIMARY_AUTHENTIC_UTTERANCE
    if status_value == ClaimStatus.SUPPORTED.value:
        if kind == SupportKind.PRIMARY_SOURCE or primary_access == "found_relevant":
            return ReasonCode.DOCUMENTARY_PRIMARY
        if kind == SupportKind.INDEPENDENT_REPORTING or known_independent >= 2:
            return ReasonCode.INDEPENDENT_CORROBORATION
        if authoritative_independent:
            return ReasonCode.DOCUMENTARY_PRIMARY
        return ReasonCode.INSUFFICIENT_EVIDENCE
    if known_independent == 1:
        return ReasonCode.SINGLE_KNOWN_ORIGIN
    if unknown_groups:
        return ReasonCode.INDEPENDENCE_NOT_ESTABLISHED
    return ReasonCode.INSUFFICIENT_EVIDENCE


def render_reason(code: ReasonCode | None, context: ReasonContext) -> str | None:
    if code is None:
        return None
    known = int(context.known_independent or 0)
    unknown = int(context.unknown_groups or 0)
    status = context.status
    if code is ReasonCode.MISSING_DOCUMENTARY_PRIMARY:
        return (
            "No hay fuente primaria documental que sostenga la proposición; "
            "el estado refleja un techo de certeza, no varias corroboraciones."
        )
    if code is ReasonCode.MISSING_AUTHENTIC_PRIMARY:
        return "No hay publicación original auténtica del dicho; un medio que atribuye no alcanza para promoverla."
    if code is ReasonCode.INDEPENDENCE_NOT_ESTABLISHED:
        return (
            f"Independencia no demostrada ({unknown} grupo(s) desconocido(s), "
            f"{known} origen(es) conocido(s))."
        )
    if code is ReasonCode.SINGLE_KNOWN_ORIGIN:
        if context.demotion == Demotion.INSUFFICIENT_INDEPENDENCE:
            return f"Un origen informativo conocido no alcanza para corroboración independiente ({status})."
        return "Un origen informativo conocido sostiene la proposición."
    if code is ReasonCode.PARTIAL_SUPPORT:
        return "La evidencia solo sostiene parte de la proposición."
    if code is ReasonCode.MIXED_CLAIM_NO_EXCEPTION:
        return "La proposición sigue mixta; no se aplicó la excepción de declaración."
    if code is ReasonCode.PRIMARY_AUTHENTIC_UTTERANCE:
        return "Una fuente primaria auténtica documenta el dicho, no el contenido de lo afirmado."
    if code is ReasonCode.DOCUMENTARY_PRIMARY:
        return "Una fuente primaria documental sostiene la proposición."
    if code is ReasonCode.INDEPENDENT_CORROBORATION:
        if context.authoritative_independent:
            return f"{known} orígenes informativos distintos sostienen la proposición."
        return f"{known} coberturas periodísticas independientes sostienen la proposición."
    if code is ReasonCode.CONFLICTING_COMPARABLE_EVIDENCE:
        return "Hay evidencias comparables en conflicto sobre la proposición evaluada."
    if code is ReasonCode.COMPARABLE_DISPROOF:
        return "Una contradicción con correspondencia comprobada de proposición y contexto refuta el claim."
    if code is ReasonCode.CONTRADICTION_NOT_COMPARABLE:
        return "No se acreditó una contradicción pertinente y comparable de la proposición evaluada."
    return "Evidencia insuficiente para corroborar de forma independiente."


def _first_fragment_in_text(fragments: list[str], text: str) -> str | None:
    for raw in fragments:
        part = (raw or "").strip()
        if part and part in text:
            return part
    return None


def editorial_scopes(
    *,
    evaluated_text: str | None,
    status: str,
    demotion: Demotion | str = Demotion.NONE,
    evidence_types: list[str] | None = None,
    qualify_fragments: list[str] | None = None,
) -> tuple[str | None, str | None]:
    """Return (verified_scope, unsupported_scope) from structured evidence only.

    QUALIFIES alone does not identify which component is A or B. A claim_fragment
    that is a proper subset of evaluated text may set verified_scope. The rest
    of the compound is unsupported_scope=None (undetermined), not a C8 split.
    SINGLE_SOURCE or SUPPORTED without admitted SUPPORTS does not identify a
    verified scope; the status token is not a substitute for that evidence.
    """
    text = (evaluated_text or "").strip()
    if not text:
        return None, None
    status_value = _enum_value(status) or str(status)
    demotion_value = _demotion(demotion)
    types = {_enum_value(item) for item in (evidence_types or []) if item}
    fragments = [str(item).strip() for item in (qualify_fragments or []) if str(item).strip()]
    has_supports = EvidenceType.SUPPORTS.value in types
    has_qualifies = EvidenceType.QUALIFIES.value in types or bool(fragments)
    if status_value in {
        ClaimStatus.DISPROVEN.value,
        ClaimStatus.CONFLICTING.value,
        ClaimStatus.UNCERTAIN.value,
        ClaimStatus.OUTDATED.value,
    }:
        return None, text
    if demotion_value == Demotion.PARTIAL_SUPPORT or (has_qualifies and not has_supports):
        established = _first_fragment_in_text(fragments, text)
        if established and established != text:
            return established, None
        return None, None
    if has_supports:
        return text, None
    return None, None


def qualify_fragments_from_checks(checks: list[dict] | None) -> list[str]:
    fragments: list[str] = []
    for row in checks or []:
        if not isinstance(row, dict):
            continue
        admitted = str(row.get("admitted") or "")
        if admitted != EvidenceType.QUALIFIES.value:
            continue
        value = row.get("claim_fragment")
        if value:
            fragments.append(str(value))
    return fragments


def evidence_type_values(claim: Any) -> list[str]:
    values: list[str] = []
    for row in getattr(claim, "evidence", None) or []:
        raw = getattr(row, "evidence_type", None)
        token = _enum_value(raw)
        if token:
            values.append(token)
    return values


def public_resolution_fields(decision: dict[str, Any] | None) -> dict[str, Any]:
    empty = {"reason_code": None, "verified_scope": None, "unsupported_scope": None}
    if not evaluation_is_complete(decision):
        return empty
    return {
        "reason_code": read_reason_code(decision).value if read_reason_code(decision) else None,
        "verified_scope": decision.get("verified_scope"),
        "unsupported_scope": decision.get("unsupported_scope"),
    }
