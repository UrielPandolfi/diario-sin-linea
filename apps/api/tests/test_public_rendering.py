from app.domain.enums import ClaimStatus
from app.schemas.editorial_evidence import (
    ClaimDecision,
    Demotion,
    EvaluationState,
    PropositionRole,
    PublicRendering,
    ReasonCode,
    StatementEvidenceClass,
    SupportBasis,
    SupportKind,
)
from app.services.public_rendering import public_rendering_for, public_rendering_payload

_COMPLETE = EvaluationState.COMPLETE


def test_supported_independent_reporting_allows_categorical_and_confirmation() -> None:
    got = public_rendering_for(
        status=ClaimStatus.SUPPORTED.value,
        evaluation_state=_COMPLETE,
        support_basis=SupportBasis(
            kind=SupportKind.INDEPENDENT_REPORTING.value,
            known_independent_count=2,
            demotion=Demotion.NONE.value,
        ),
        reason_code=ReasonCode.INDEPENDENT_CORROBORATION,
    )
    assert got == PublicRendering(
        attribution_required=False,
        categorical_allowed=True,
        headline_unattributed_allowed=True,
        independent_confirmation_language_allowed=True,
    )
    again = public_rendering_for(
        status=ClaimStatus.SUPPORTED.value,
        evaluation_state=_COMPLETE,
        support_basis=SupportBasis(
            kind=SupportKind.INDEPENDENT_REPORTING.value,
            known_independent_count=2,
            demotion=Demotion.NONE.value,
        ),
        reason_code=ReasonCode.INDEPENDENT_CORROBORATION,
    )
    assert again == got


def test_single_source_complete_requires_attribution() -> None:
    got = public_rendering_for(
        status=ClaimStatus.SINGLE_SOURCE.value,
        evaluation_state=_COMPLETE,
        support_basis=SupportBasis(
            kind=SupportKind.SINGLE_REPORT.value,
            known_independent_count=1,
            demotion=Demotion.INSUFFICIENT_INDEPENDENCE.value,
        ),
        reason_code=ReasonCode.SINGLE_KNOWN_ORIGIN,
    )
    assert got == PublicRendering(
        attribution_required=True,
        categorical_allowed=False,
        headline_unattributed_allowed=False,
        independent_confirmation_language_allowed=False,
    )


def test_authentic_primary_utterance_keeps_speaker_without_independent_language() -> None:
    got = public_rendering_for(
        status=ClaimStatus.SUPPORTED.value,
        evaluation_state=_COMPLETE,
        support_basis=SupportBasis(
            kind=SupportKind.PRIMARY_SOURCE.value,
            statement_evidence_class=StatementEvidenceClass.AUTHENTIC_PRIMARY.value,
            known_independent_count=2,
            demotion=Demotion.NONE.value,
        ),
        proposition_role=PropositionRole.UTTERANCE,
        reason_code=ReasonCode.PRIMARY_AUTHENTIC_UTTERANCE,
    )
    assert got.categorical_allowed is True
    assert got.attribution_required is True
    assert got.headline_unattributed_allowed is False
    assert got.independent_confirmation_language_allowed is False


def test_documentary_primary_does_not_enable_independent_language() -> None:
    got = public_rendering_for(
        status=ClaimStatus.SUPPORTED.value,
        evaluation_state=_COMPLETE,
        support_basis=SupportBasis(
            kind=SupportKind.PRIMARY_SOURCE.value,
            primary_access="found_relevant",
            known_independent_count=1,
            demotion=Demotion.NONE.value,
        ),
        reason_code=ReasonCode.DOCUMENTARY_PRIMARY,
    )
    assert got.categorical_allowed is True
    assert got.headline_unattributed_allowed is True
    assert got.independent_confirmation_language_allowed is False


def test_partial_support_does_not_allow_full_proposition_as_categorical() -> None:
    got = public_rendering_for(
        status=ClaimStatus.SINGLE_SOURCE.value,
        evaluation_state=_COMPLETE,
        support_basis=SupportBasis(
            kind=SupportKind.SINGLE_REPORT.value,
            demotion=Demotion.NONE.value,
            evaluated_canonical_text="El decreto elimina el régimen y entra en vigencia mañana",
            documents_qualifying=1,
            documents_supporting=0,
        ),
        reason_code=ReasonCode.PARTIAL_SUPPORT,
        verified_scope="El decreto elimina el régimen",
        unsupported_scope=None,
    )
    assert got.categorical_allowed is False
    assert got.headline_unattributed_allowed is False
    assert got.independent_confirmation_language_allowed is False


def test_uncertain_conflicting_disproven_are_not_categorical() -> None:
    for status, code in (
        (ClaimStatus.UNCERTAIN.value, ReasonCode.INSUFFICIENT_EVIDENCE),
        (ClaimStatus.CONFLICTING.value, ReasonCode.CONFLICTING_COMPARABLE_EVIDENCE),
        (ClaimStatus.DISPROVEN.value, ReasonCode.COMPARABLE_DISPROOF),
    ):
        got = public_rendering_for(
            status=status,
            evaluation_state=_COMPLETE,
            reason_code=code,
        )
        assert got.categorical_allowed is False
        assert got.headline_unattributed_allowed is False
        assert got.independent_confirmation_language_allowed is False


def test_skipped_and_legacy_do_not_receive_complete_permissions() -> None:
    skipped = public_rendering_for(
        status=ClaimStatus.SINGLE_SOURCE.value,
        evaluation_state=EvaluationState.SKIPPED,
        reason_code=ReasonCode.INSUFFICIENT_EVIDENCE,
    )
    assert skipped is None
    legacy = public_rendering_for(
        status=ClaimStatus.SUPPORTED.value,
        evaluation_state=None,
        support_basis=SupportBasis(kind=SupportKind.INDEPENDENT_REPORTING.value, known_independent_count=2),
        reason_code=ReasonCode.INDEPENDENT_CORROBORATION,
    )
    assert legacy is None
    pending = public_rendering_for(status=ClaimStatus.SUPPORTED.value, evaluation_state=EvaluationState.PENDING)
    assert pending is None


def test_missing_public_rendering_parses_without_granting_flags() -> None:
    raw = {
        "claim_id": "legacy",
        "status": "SUPPORTED",
        "evaluation_state": "complete",
        "support_basis": {"kind": "independent_reporting", "known_independent_count": 2},
    }
    decision = ClaimDecision.model_validate(raw)
    assert decision.public_rendering is None
    assert public_rendering_payload(raw) is None
    junk = ClaimDecision.model_validate({**raw, "public_rendering": "nope"})
    assert junk.public_rendering is None
    skipped = {
        "claim_id": "skipped",
        "status": "SINGLE_SOURCE",
        "evaluation_state": "skipped",
        "public_rendering": {
            "attribution_required": False,
            "categorical_allowed": True,
            "headline_unattributed_allowed": True,
            "independent_confirmation_language_allowed": True,
        },
    }
    assert public_rendering_payload(skipped) is None
