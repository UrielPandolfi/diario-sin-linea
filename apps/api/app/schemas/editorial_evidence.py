from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, Field, ValidationError

CONTRACT_VERSION = "editorial-evidence-1"


class PropositionRole(StrEnum):
    EXISTENCE = "existence"
    ATTRIBUTED_CONTENT = "attributed_content"
    ACCUSATION_TRUTH = "accusation_truth"
    UTTERANCE = "utterance"
    NORMATIVE_SCOPE = "normative_scope"
    EFFECTIVE_DATE = "effective_date"
    OTHER = "other"


class CoverageMatch(StrEnum):
    EQUIVALENT = "equivalent"
    PARTIAL = "partial"
    NONE = "none"


class CoverageSignal(StrEnum):
    TITLE = "title"
    LEAD = "lead"


class GapReason(StrEnum):
    NOT_EXTRACTED = "not_extracted"
    DROPPED_INVALID_EXCERPT = "dropped_invalid_excerpt"
    MERGED_AWAY = "merged_away"
    QUALIFIER_MISMATCH = "qualifier_mismatch"
    RECOVERY_FAILED = "recovery_failed"
    EMPTY_CANONICAL = "empty_canonical"
    EMPTY_KEY = "empty_key"


class DropReason(StrEnum):
    EMPTY_CANONICAL = "empty_canonical"
    INVALID_EXCERPT = "invalid_excerpt"
    EMPTY_KEY = "empty_key"
    MERGED_INTO = "merged_into"


class StatementEvidenceClass(StrEnum):
    AUTHENTIC_PRIMARY = "authentic_primary"
    ATTRIBUTED_REPORT = "attributed_report"
    ACCESS_LIMITED = "access_limited"
    SEARCH_HIT_ONLY = "search_hit_only"
    NOT_RELEVANT = "not_relevant"


class DocumentClass(StrEnum):
    CONSTITUTIVE = "constitutive"
    OWN_PUBLICATION = "own_publication"
    ATTRIBUTED_REPORT = "attributed_report"
    SEARCH_HIT_ONLY = "search_hit_only"
    ACCESS_FAILED = "access_failed"


class Demotion(StrEnum):
    NONE = "none"
    INSUFFICIENT_INDEPENDENCE = "insufficient_independence"
    UNPROVEN_INDEPENDENCE = "unproven_independence"
    MISSING_AUTHENTIC_PRIMARY = "missing_authentic_primary"
    MISSING_DOCUMENTARY_PRIMARY = "missing_documentary_primary"
    PARTIAL_SUPPORT = "partial_support"
    MIXED_CLAIM_NO_EXCEPTION = "mixed_claim_no_exception"


class PrimaryAccess(StrEnum):
    FOUND_RELEVANT = "found_relevant"
    FOUND_UNRELATED = "found_unrelated"
    NOT_FOUND = "not_found"
    ACCESS_FAILED = "access_failed"


class SupportKind(StrEnum):
    PRIMARY_SOURCE = "primary_source"
    INDEPENDENT_REPORTING = "independent_reporting"
    SINGLE_REPORT = "single_report"
    ATTRIBUTED_STATEMENT = "attributed_statement"
    CONFLICTING_EVIDENCE = "conflicting_evidence"
    INSUFFICIENT = "insufficient"


class ReasonCode(StrEnum):
    """Deterministic editorial cause. Missing on legacy snapshots.

    Mapped from Demotion, SupportKind, admitted contradiction gates and
    independence counts already computed in code. Never from LLM prose.
    """

    INDEPENDENCE_NOT_ESTABLISHED = "INDEPENDENCE_NOT_ESTABLISHED"
    SINGLE_KNOWN_ORIGIN = "SINGLE_KNOWN_ORIGIN"
    MISSING_DOCUMENTARY_PRIMARY = "MISSING_DOCUMENTARY_PRIMARY"
    MISSING_AUTHENTIC_PRIMARY = "MISSING_AUTHENTIC_PRIMARY"
    PRIMARY_AUTHENTIC_UTTERANCE = "PRIMARY_AUTHENTIC_UTTERANCE"
    DOCUMENTARY_PRIMARY = "DOCUMENTARY_PRIMARY"
    INDEPENDENT_CORROBORATION = "INDEPENDENT_CORROBORATION"
    PARTIAL_SUPPORT = "PARTIAL_SUPPORT"
    MIXED_CLAIM_NO_EXCEPTION = "MIXED_CLAIM_NO_EXCEPTION"
    CONFLICTING_COMPARABLE_EVIDENCE = "CONFLICTING_COMPARABLE_EVIDENCE"
    COMPARABLE_DISPROOF = "COMPARABLE_DISPROOF"
    CONTRADICTION_NOT_COMPARABLE = "CONTRADICTION_NOT_COMPARABLE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class EvaluationState(StrEnum):
    """Persisted verification evaluation state. Missing on legacy snapshots.

    PENDING and FAILED exist on the contract but current SUCCESS runs do not
    write them: a RUNNING pipeline is not a snapshot, and a failed verify
    leaves PipelineStatus.FAILED without decision_by_claim_id.
    """

    COMPLETE = "complete"
    SKIPPED = "skipped"
    PENDING = "pending"
    FAILED = "failed"


def _coerce_evaluation_state(value: Any) -> EvaluationState | None:
    if value is None or value == "":
        return None
    if isinstance(value, EvaluationState):
        return value
    try:
        return EvaluationState(str(value).strip().lower())
    except ValueError:
        return None


OptionalEvaluationState = Annotated[
    EvaluationState | None,
    BeforeValidator(_coerce_evaluation_state),
]


def _coerce_reason_code(value: Any) -> ReasonCode | None:
    if value is None or value == "":
        return None
    if isinstance(value, ReasonCode):
        return value
    try:
        return ReasonCode(str(value).strip())
    except ValueError:
        return None


OptionalReasonCode = Annotated[
    ReasonCode | None,
    BeforeValidator(_coerce_reason_code),
]


class ExpectedCentral(BaseModel):
    proposition: str
    role: PropositionRole = PropositionRole.OTHER
    subject: str | None = None
    act: str | None = None
    object_text: str | None = None
    attribution: str | None = None
    negation: bool = False
    qualifiers: list[str] = Field(default_factory=list)
    signal: CoverageSignal = CoverageSignal.TITLE
    match_claim_id: str | None = None
    match: CoverageMatch = CoverageMatch.NONE
    gap_reason: str | None = None


class DroppedExtracted(BaseModel):
    canonical_text: str
    reason: str
    assertion_key: str | None = None
    merged_into: str | None = None


class CoverageContract(BaseModel):
    contract_version: str = CONTRACT_VERSION
    expected_central: list[ExpectedCentral] = Field(default_factory=list)
    spine_claim_ids: list[str] = Field(default_factory=list)
    persisted_assertion_keys: list[str] = Field(default_factory=list)
    dropped: list[DroppedExtracted] = Field(default_factory=list)
    proposition_role: dict[str, str] = Field(default_factory=dict)
    source_quality: list[dict[str, Any]] = Field(default_factory=list)
    coverage_gap: bool = False
    verification_incomplete: bool = False


class EvaluatedClaim(BaseModel):
    claim_id: str
    canonical_text: str
    assertion_key: str
    status: str
    role: str | None = None


class VerificationBudget(BaseModel):
    limit: int
    selected_ids: list[str] = Field(default_factory=list)
    deferred: list[dict[str, str]] = Field(default_factory=list)
    central_unverified: list[str] = Field(default_factory=list)


class SupportBasis(BaseModel):
    known_independent_count: int = 0
    unknown_group_count: int = 0
    reprint_collapsed_count: int = 0
    documents_consulted: int = 0
    documents_supporting: int = 0
    documents_qualifying: int = 0
    documents_contradicting: int = 0
    origin_groups_known: int = 0
    origin_groups_unknown: int = 0
    statement_evidence_class: str | None = None
    primary_access: str | None = None
    kind: str | None = None
    demotion: str = Demotion.NONE.value
    evaluated_canonical_text: str | None = None
    document_keys: list[str] = Field(default_factory=list)
    information_origins: list[str] = Field(default_factory=list)


class PublicRendering(BaseModel):
    """Presentation permissions for the evaluated proposition. Not a publish license.

    None on a field (or a missing PublicRendering) means undetermined: skipped,
    pending, failed, or unknown/legacy. False forbids; True permits only within
    the proposition's legitimate scope.

    attribution_required: keep source or speaker attribution required by the support.
    categorical_allowed: may assert the evaluated proposition as fact within that
        scope. Does not authorize widening the claim, dropping modality, or treating
        declared content as true.
    headline_unattributed_allowed: may put that proposition in the headline without
        the attribution its support requires.
    independent_confirmation_language_allowed: independent-corroboration wording
        only when structured provenance already accredits it.
    """

    attribution_required: bool | None = None
    categorical_allowed: bool | None = None
    headline_unattributed_allowed: bool | None = None
    independent_confirmation_language_allowed: bool | None = None


def _coerce_public_rendering(value: Any) -> PublicRendering | None:
    if value is None or value == "":
        return None
    if isinstance(value, PublicRendering):
        return value
    if isinstance(value, dict):
        try:
            return PublicRendering.model_validate(value)
        except ValidationError:
            return None
    return None


OptionalPublicRendering = Annotated[
    PublicRendering | None,
    BeforeValidator(_coerce_public_rendering),
]


class ClaimDecision(BaseModel):
    claim_id: str
    status: str
    unresolved: bool = False
    final_reason: str | None = None
    llm_reason: str | None = None
    support_basis: SupportBasis = Field(default_factory=SupportBasis)
    proposition_role: str | None = None
    evaluation_state: OptionalEvaluationState = None
    reason_code: OptionalReasonCode = None
    verified_scope: str | None = None
    unsupported_scope: str | None = None
    public_rendering: OptionalPublicRendering = None


def read_public_rendering(decision: ClaimDecision | dict[str, Any] | None) -> PublicRendering | None:
    """None if absent, invalid, or not a complete evaluation. Never infers True."""
    if decision is None:
        return None
    if not evaluation_is_complete(decision):
        return None
    if isinstance(decision, ClaimDecision):
        return decision.public_rendering
    raw = decision.get("public_rendering") if isinstance(decision, dict) else None
    return _coerce_public_rendering(raw)


def read_reason_code(decision: ClaimDecision | dict[str, Any] | None) -> ReasonCode | None:
    """None means unknown/legacy. Never infers a stronger cause."""
    if decision is None:
        return None
    if isinstance(decision, ClaimDecision):
        return decision.reason_code
    raw = decision.get("reason_code") if isinstance(decision, dict) else None
    return _coerce_reason_code(raw)


def read_evaluation_state(decision: ClaimDecision | dict[str, Any] | None) -> EvaluationState | None:
    """None means unknown/legacy. Never defaults to COMPLETE."""
    if decision is None:
        return None
    if isinstance(decision, ClaimDecision):
        return decision.evaluation_state
    raw = decision.get("evaluation_state") if isinstance(decision, dict) else None
    return _coerce_evaluation_state(raw)


_SKIP_LLM_REASONS = frozenset({"veto", "policy_skip", "budget", "outside_recheck"})


def _decision_llm_reason(decision: ClaimDecision | dict[str, Any] | None) -> str:
    if decision is None:
        return ""
    if isinstance(decision, ClaimDecision):
        return str(decision.llm_reason or "")
    if isinstance(decision, dict):
        return str(decision.get("llm_reason") or "")
    return ""


def decision_looks_like_skip(decision: ClaimDecision | dict[str, Any] | None) -> bool:
    """Skip-shaped even without evaluation_state (C1 persistía reason en llm_reason)."""
    state = read_evaluation_state(decision)
    if state is EvaluationState.SKIPPED:
        return True
    if state is not None:
        return False
    return _decision_llm_reason(decision) in _SKIP_LLM_REASONS


def evaluation_is_complete(decision: ClaimDecision | dict[str, Any] | None) -> bool:
    return read_evaluation_state(decision) == EvaluationState.COMPLETE


def decision_was_evaluated(decision: ClaimDecision | dict[str, Any] | None) -> bool:
    """True only for an editorial evaluation, never for skip/pending/failed.

    Legacy snapshots omitted skipped claims from decision_by_claim_id, so a stored
    decision without evaluation_state is treated as evaluated copy if it is not
    skip-shaped. Presence of a decision alone is not enough after C1, because
    skipped rows also occupy that map. Justifying the legacy evaluated copy:
    support_basis / status written by _decision_after_policy, and the absence of
    a skip reason (veto, policy_skip, budget, outside_recheck).
    """
    state = read_evaluation_state(decision)
    if state is EvaluationState.COMPLETE:
        return True
    if state in {EvaluationState.SKIPPED, EvaluationState.PENDING, EvaluationState.FAILED}:
        return False
    if decision is None:
        return False
    if decision_looks_like_skip(decision):
        return False
    return True


class EvidenceContract(BaseModel):
    contract_version: str = CONTRACT_VERSION
    claims_fingerprint: str | None = None
    based_on_claim_run_id: str | None = None
    coverage: CoverageContract | None = None
    evaluated_claims: list[EvaluatedClaim] = Field(default_factory=list)
    decision_by_claim_id: dict[str, ClaimDecision] = Field(default_factory=dict)
    verification_budget: VerificationBudget | None = None
    stale_verification: bool = False
