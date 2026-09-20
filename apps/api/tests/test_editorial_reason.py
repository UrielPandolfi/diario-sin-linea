from types import SimpleNamespace

from app.domain.enums import ClaimStatus, EvidenceType
from app.schemas.editorial_evidence import (
    ClaimDecision,
    Demotion,
    EvidenceContract,
    ReasonCode,
    StatementEvidenceClass,
    SupportKind,
    read_reason_code,
)
from app.services.editorial_reason import (
    ReasonContext,
    editorial_scopes,
    reason_code_for,
    render_reason,
)
from app.services.information_origin import demotion_for


def test_demotion_maps_to_stable_reason_code_and_render() -> None:
    assessment = SimpleNamespace(
        known_independent=1,
        unknown_groups=2,
        authoritative_independent=0,
        documents_supporting=1,
        documents_qualifying=0,
        statement_evidence_class=None,
    )
    expected = [
        (Demotion.UNPROVEN_INDEPENDENCE, ReasonCode.INDEPENDENCE_NOT_ESTABLISHED, "Independencia no demostrada"),
        (Demotion.INSUFFICIENT_INDEPENDENCE, ReasonCode.SINGLE_KNOWN_ORIGIN, "origen informativo conocido"),
        (Demotion.MISSING_DOCUMENTARY_PRIMARY, ReasonCode.MISSING_DOCUMENTARY_PRIMARY, "primaria documental"),
        (Demotion.MISSING_AUTHENTIC_PRIMARY, ReasonCode.MISSING_AUTHENTIC_PRIMARY, "publicación original auténtica"),
        (Demotion.PARTIAL_SUPPORT, ReasonCode.PARTIAL_SUPPORT, "solo sostiene parte"),
        (Demotion.MIXED_CLAIM_NO_EXCEPTION, ReasonCode.MIXED_CLAIM_NO_EXCEPTION, "sigue mixta"),
    ]
    for demotion, code, snippet in expected:
        got = reason_code_for(
            status=ClaimStatus.SINGLE_SOURCE.value,
            demotion=demotion,
            known_independent=assessment.known_independent,
            unknown_groups=assessment.unknown_groups,
        )
        assert got is code
        text = render_reason(
            got,
            ReasonContext(
                status=ClaimStatus.SINGLE_SOURCE.value,
                demotion=demotion,
                known_independent=assessment.known_independent,
                unknown_groups=assessment.unknown_groups,
            ),
        )
        assert snippet.casefold() in (text or "").casefold()


def test_independence_success_and_utterance_primary_codes() -> None:
    assert (
        reason_code_for(
            status=ClaimStatus.SUPPORTED.value,
            demotion=Demotion.NONE,
            known_independent=2,
            support_kind=SupportKind.INDEPENDENT_REPORTING,
        )
        is ReasonCode.INDEPENDENT_CORROBORATION
    )
    assert (
        reason_code_for(
            status=ClaimStatus.SUPPORTED.value,
            demotion=Demotion.NONE,
            statement_evidence_class=StatementEvidenceClass.AUTHENTIC_PRIMARY,
            support_kind=SupportKind.PRIMARY_SOURCE,
            known_independent=2,
        )
        is ReasonCode.PRIMARY_AUTHENTIC_UTTERANCE
    )
    assert (
        reason_code_for(
            status=ClaimStatus.SUPPORTED.value,
            demotion=Demotion.NONE,
            primary_access="found_relevant",
            support_kind=SupportKind.PRIMARY_SOURCE,
        )
        is ReasonCode.DOCUMENTARY_PRIMARY
    )


def test_skipped_and_legacy_do_not_get_evaluated_reason_or_scopes() -> None:
    from app.services.editorial_reason import public_resolution_fields

    skipped = {
        "claim_id": "skipped",
        "status": "SINGLE_SOURCE",
        "evaluation_state": "skipped",
        "llm_reason": "policy_skip",
        "reason_code": ReasonCode.INSUFFICIENT_EVIDENCE.value,
        "verified_scope": "no debería usarse",
        "unsupported_scope": "tampoco",
        "support_basis": {},
    }
    assert public_resolution_fields(skipped) == {
        "reason_code": None,
        "verified_scope": None,
        "unsupported_scope": None,
    }
    legacy = {
        "claim_id": "legacy",
        "status": "SINGLE_SOURCE",
        "support_basis": {"known_independent_count": 1},
    }
    fields = public_resolution_fields(legacy)
    assert fields["reason_code"] is None
    assert fields["verified_scope"] is None
    assert fields["unsupported_scope"] is None


def test_contradiction_gates_map_without_changing_comparability() -> None:
    assert (
        reason_code_for(status=ClaimStatus.DISPROVEN.value, demotion=Demotion.NONE)
        is ReasonCode.COMPARABLE_DISPROOF
    )
    assert (
        reason_code_for(status=ClaimStatus.CONFLICTING.value, demotion=Demotion.NONE)
        is ReasonCode.CONFLICTING_COMPARABLE_EVIDENCE
    )
    assert (
        reason_code_for(
            status=ClaimStatus.UNCERTAIN.value,
            demotion=Demotion.NONE,
            rejected_disproof=True,
        )
        is ReasonCode.CONTRADICTION_NOT_COMPARABLE
    )
    text = render_reason(
        ReasonCode.CONTRADICTION_NOT_COMPARABLE,
        ReasonContext(status=ClaimStatus.UNCERTAIN.value, rejected_disproof=True),
    )
    assert "contradicción pertinente" in (text or "")


def test_qualifies_partial_scopes_do_not_verify_the_whole_claim() -> None:
    established = "El decreto elimina el régimen"
    claim_text = f"{established} y entra en vigencia mañana"
    verified, unsupported = editorial_scopes(
        evaluated_text=claim_text,
        status=ClaimStatus.SINGLE_SOURCE.value,
        demotion=Demotion.NONE,
        evidence_types=[EvidenceType.QUALIFIES.value],
        qualify_fragments=[established],
    )
    assert verified == established
    assert unsupported is None
    assert verified != claim_text
    assert reason_code_for(
        status=ClaimStatus.SINGLE_SOURCE.value,
        demotion=Demotion.NONE,
        documents_qualifying=1,
        documents_supporting=0,
    ) is ReasonCode.PARTIAL_SUPPORT


def test_qualifies_without_fragment_does_not_invent_verified_scope() -> None:
    text = "A y B"
    verified, unsupported = editorial_scopes(
        evaluated_text=text,
        status=ClaimStatus.SINGLE_SOURCE.value,
        evidence_types=[EvidenceType.QUALIFIES.value],
        qualify_fragments=[],
    )
    assert verified is None
    assert unsupported is None


def test_single_source_without_admitted_supports_does_not_verify_the_claim() -> None:
    text = "Pérez afirmó que el costo será de 40.000 millones"
    for types in ([EvidenceType.MENTIONS.value], []):
        verified, unsupported = editorial_scopes(
            evaluated_text=text,
            status=ClaimStatus.SINGLE_SOURCE.value,
            evidence_types=types,
        )
        assert verified is None
        assert unsupported is None
        assert verified != text


def test_single_source_with_admitted_supports_verifies_the_claim() -> None:
    text = "Hubo un incendio en el depósito de Rosario"
    verified, unsupported = editorial_scopes(
        evaluated_text=text,
        status=ClaimStatus.SINGLE_SOURCE.value,
        evidence_types=[EvidenceType.SUPPORTS.value],
    )
    assert verified == text
    assert unsupported is None


def test_legacy_decision_parses_without_reason_or_scopes() -> None:
    raw = {
        "claim_id": "legacy",
        "status": "SINGLE_SOURCE",
        "unresolved": False,
        "support_basis": {"known_independent_count": 1},
    }
    decision = ClaimDecision.model_validate(raw)
    assert decision.reason_code is None
    assert decision.verified_scope is None
    assert decision.unsupported_scope is None
    assert read_reason_code(raw) is None
    assert read_reason_code({**raw, "reason_code": "not-a-code"}) is None
    contract = EvidenceContract.model_validate({"contract_version": "editorial-evidence-1", "decision_by_claim_id": {"legacy": raw}})
    assert contract.decision_by_claim_id["legacy"].reason_code is None


def test_demotion_for_independence_is_unchanged() -> None:
    assessment = SimpleNamespace(known_independent=1, unknown_groups=0, authoritative_independent=0)
    assert (
        demotion_for(
            desired_status="SUPPORTED",
            final_status="SINGLE_SOURCE",
            assessment=assessment,
            primary_required=False,
            primary_supports=False,
            mixed=False,
            role=None,
        )
        is Demotion.INSUFFICIENT_INDEPENDENCE
    )
