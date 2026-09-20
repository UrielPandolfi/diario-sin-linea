from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from app.domain.enums import ClaimStatus
from app.schemas.editorial_evidence import (
    Demotion,
    EvaluationState,
    PropositionRole,
    PublicRendering,
    ReasonCode,
    StatementEvidenceClass,
    SupportBasis,
    SupportKind,
    read_evaluation_state,
    read_reason_code,
)

_RESTRICTED = PublicRendering(
    attribution_required=True,
    categorical_allowed=False,
    headline_unattributed_allowed=False,
    independent_confirmation_language_allowed=False,
)

_RESTRICTED_CODES = {
    ReasonCode.PARTIAL_SUPPORT,
    ReasonCode.MIXED_CLAIM_NO_EXCEPTION,
    ReasonCode.INDEPENDENCE_NOT_ESTABLISHED,
    ReasonCode.SINGLE_KNOWN_ORIGIN,
    ReasonCode.MISSING_DOCUMENTARY_PRIMARY,
    ReasonCode.MISSING_AUTHENTIC_PRIMARY,
    ReasonCode.INSUFFICIENT_EVIDENCE,
    ReasonCode.CONFLICTING_COMPARABLE_EVIDENCE,
    ReasonCode.COMPARABLE_DISPROOF,
    ReasonCode.CONTRADICTION_NOT_COMPARABLE,
}


def _enum_value(value: Any) -> str:
    if value is None:
        return ""
    return str(value.value) if hasattr(value, "value") else str(value)


def _basis(value: SupportBasis | dict[str, Any] | None) -> SupportBasis:
    if isinstance(value, SupportBasis):
        return value
    if isinstance(value, dict):
        try:
            return SupportBasis.model_validate(value)
        except ValidationError:
            return SupportBasis()
    return SupportBasis()


def _is_partial(
    *,
    code: ReasonCode | None,
    basis: SupportBasis,
    verified_scope: str | None,
    unsupported_scope: str | None,
) -> bool:
    if code is ReasonCode.PARTIAL_SUPPORT or _enum_value(basis.demotion) == Demotion.PARTIAL_SUPPORT.value:
        return True
    if unsupported_scope:
        return True
    evaluated = (basis.evaluated_canonical_text or "").strip()
    verified = (verified_scope or "").strip()
    return bool(verified and evaluated and verified != evaluated)


def _independent_language(basis: SupportBasis, code: ReasonCode | None) -> bool:
    if code is ReasonCode.PRIMARY_AUTHENTIC_UTTERANCE:
        return False
    if (basis.statement_evidence_class or "") == StatementEvidenceClass.AUTHENTIC_PRIMARY.value:
        return False
    kind = _enum_value(basis.kind)
    known = int(basis.known_independent_count or 0)
    return kind == SupportKind.INDEPENDENT_REPORTING.value and known >= 2


def public_rendering_for(
    *,
    status: str,
    evaluation_state: EvaluationState | str | None = None,
    support_basis: SupportBasis | dict[str, Any] | None = None,
    proposition_role: str | PropositionRole | None = None,
    reason_code: ReasonCode | str | None = None,
    verified_scope: str | None = None,
    unsupported_scope: str | None = None,
) -> PublicRendering | None:
    """Pure mapping from structured editorial fields. No I/O, LLM, or article text."""
    state = read_evaluation_state({"evaluation_state": _enum_value(evaluation_state) or evaluation_state})
    if state is not EvaluationState.COMPLETE:
        return None
    status_value = _enum_value(status) or str(status)
    code = read_reason_code({"reason_code": _enum_value(reason_code) or reason_code})
    basis = _basis(support_basis)
    role = _enum_value(proposition_role)
    if _is_partial(code=code, basis=basis, verified_scope=verified_scope, unsupported_scope=unsupported_scope):
        return _RESTRICTED
    if code in _RESTRICTED_CODES:
        return _RESTRICTED
    if status_value in {
        ClaimStatus.UNCERTAIN.value,
        ClaimStatus.CONFLICTING.value,
        ClaimStatus.DISPROVEN.value,
        ClaimStatus.OUTDATED.value,
        ClaimStatus.SINGLE_SOURCE.value,
    }:
        return _RESTRICTED
    if status_value != ClaimStatus.SUPPORTED.value:
        return _RESTRICTED
    utterance = role == PropositionRole.UTTERANCE.value or (
        (basis.statement_evidence_class or "") == StatementEvidenceClass.AUTHENTIC_PRIMARY.value
    )
    independent = _independent_language(basis, code)
    if utterance:
        return PublicRendering(
            attribution_required=True,
            categorical_allowed=True,
            headline_unattributed_allowed=False,
            independent_confirmation_language_allowed=independent,
        )
    return PublicRendering(
        attribution_required=False,
        categorical_allowed=True,
        headline_unattributed_allowed=True,
        independent_confirmation_language_allowed=independent,
    )


def public_rendering_payload(decision: dict[str, Any] | None) -> dict[str, Any] | None:
    from app.schemas.editorial_evidence import read_public_rendering

    rendering = read_public_rendering(decision)
    if rendering is None:
        return None
    return rendering.model_dump()
