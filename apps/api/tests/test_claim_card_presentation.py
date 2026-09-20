from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.domain.enums import ClaimStatus, EvidenceType
from app.schemas.editorial_evidence import (
    Demotion,
    PrimaryAccess,
    PropositionRole,
    ReasonCode,
    StatementEvidenceClass,
)
from app.services.claim_card_presentation import (
    AUTHENTIC_PRIMARY_LABEL,
    NOT_EVALUATED_COVERAGE,
    NOT_EVALUATED_LABEL,
    UNKNOWN_COVERAGE,
    public_copy_has_technical_tokens,
    authentic_primary_sounds_weak,
    contains_llm_reason,
    contradicts_single_source_independence,
    presentation_for_claim,
    public_presentation_payload,
)
from app.services.verification_outcome import VerificationView


def _claim(*, status: ClaimStatus, evidence=None, **overrides):
    payload = {
        "id": uuid4(),
        "canonical_text": "La afirmación",
        "status": status,
        "evidence": evidence or [],
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def _evidence(*, evidence_type: EvidenceType, name: str, url: str, source_type: str | None = None):
    return SimpleNamespace(
        evidence_type=evidence_type,
        source_item_id=uuid4(),
        source_url=url,
        source_item=SimpleNamespace(
            url=url,
            canonical_url=url,
            title=name,
            source=SimpleNamespace(name=name, domain="ejemplo.test", source_type=source_type),
        ),
    )


def _view(
    claim,
    *,
    basis: dict,
    unresolved: bool = False,
    llm_reason: str | None = None,
    evaluation_state: str | None = None,
    reason_code: str | None = None,
    proposition_role: str | None = None,
    verified_scope: str | None = None,
    unsupported_scope: str | None = None,
    public_rendering: dict | None = None,
    status: str | None = None,
) -> VerificationView:
    cid = str(claim.id)
    decision = {
        "claim_id": cid,
        "status": status or claim.status.value,
        "unresolved": unresolved,
        "llm_reason": llm_reason,
        "support_basis": basis,
    }
    if evaluation_state is not None:
        decision["evaluation_state"] = evaluation_state
    if reason_code is not None:
        decision["reason_code"] = reason_code
    if proposition_role is not None:
        decision["proposition_role"] = proposition_role
    if verified_scope is not None:
        decision["verified_scope"] = verified_scope
    if unsupported_scope is not None:
        decision["unsupported_scope"] = unsupported_scope
    if public_rendering is not None:
        decision["public_rendering"] = public_rendering
    return VerificationView(
        selected_ids={cid},
        paired=True,
        sol_by_id={
            cid: {
                "claim_id": cid,
                "status_after": claim.status.value,
                "unresolved": unresolved,
                "reason": llm_reason,
                "llm_reason": llm_reason,
            }
        },
        decision_by_claim_id={cid: decision},
    )


def _assert_safe_single_source(claim, card) -> None:
    payload = public_presentation_payload(card)
    assert not contains_llm_reason(payload)
    assert not contradicts_single_source_independence(claim.status.value, card)
    blob = " ".join(
        part for part in (card.verification_label, card.limitation, card.coverage, card.explanation) if part
    )
    assert "3 fuentes" not in blob
    assert "fuentes independientes confirman" not in blob.casefold()
    assert not public_copy_has_technical_tokens(card)


def test_three_docs_one_origin_reprint() -> None:
    docs = [
        _evidence(evidence_type=EvidenceType.SUPPORTS, name="A", url="https://a.test/1"),
        _evidence(evidence_type=EvidenceType.SUPPORTS, name="B", url="https://b.test/2"),
        _evidence(evidence_type=EvidenceType.SUPPORTS, name="C", url="https://c.test/3"),
    ]
    claim = _claim(status=ClaimStatus.SINGLE_SOURCE, evidence=docs)
    view = _view(
        claim,
        basis={
            "known_independent_count": 1,
            "unknown_group_count": 0,
            "reprint_collapsed_count": 2,
            "documents_consulted": 3,
            "documents_supporting": 3,
            "demotion": Demotion.INSUFFICIENT_INDEPENDENCE.value,
        },
        llm_reason="varias fuentes independientes confirman la denuncia",
    )
    card = presentation_for_claim(claim, view)
    assert card.verification_label == "Respaldo limitado"
    assert card.presentation_kind == "limited_support"
    assert card.basis_known is True
    assert "Se consultaron 3 documentos" in card.coverage
    assert "3 documentos respaldan" in card.coverage
    assert "restricción de procedencia" in (card.explanation or "")
    assert "3 fuentes" not in card.coverage
    assert len(card.evidence_detail) == 3
    _assert_safe_single_source(claim, card)
    payload = public_presentation_payload(card)
    assert "llm_reason" not in payload
    assert "demotion" not in payload
    assert payload["documents_consulted"] == 3
    assert payload["documents_supporting"] == 3


def test_three_docs_unknown_independence() -> None:
    docs = [
        _evidence(evidence_type=EvidenceType.SUPPORTS, name="A", url="https://a.test/1"),
        _evidence(evidence_type=EvidenceType.SUPPORTS, name="B", url="https://b.test/2"),
        _evidence(evidence_type=EvidenceType.SUPPORTS, name="C", url="https://c.test/3"),
    ]
    claim = _claim(status=ClaimStatus.SINGLE_SOURCE, evidence=docs)
    view = _view(
        claim,
        basis={
            "known_independent_count": 0,
            "unknown_group_count": 2,
            "documents_consulted": 3,
            "documents_supporting": 3,
            "demotion": Demotion.UNPROVEN_INDEPENDENCE.value,
        },
    )
    card = presentation_for_claim(claim, view)
    assert card.verification_label == "Respaldo limitado"
    assert "Se consultaron 3 documentos" in card.coverage
    assert "independencia de las procedencias" in (card.explanation or "")
    _assert_safe_single_source(claim, card)


def test_two_known_origins_corroborated() -> None:
    docs = [
        _evidence(evidence_type=EvidenceType.SUPPORTS, name="A", url="https://a.test/1", source_type="media"),
        _evidence(evidence_type=EvidenceType.SUPPORTS, name="B", url="https://b.test/2", source_type="media"),
        _evidence(evidence_type=EvidenceType.MENTIONS, name="C", url="https://c.test/3", source_type="media"),
    ]
    claim = _claim(status=ClaimStatus.SUPPORTED, evidence=docs)
    view = _view(
        claim,
        basis={
            "known_independent_count": 2,
            "unknown_group_count": 0,
            "documents_consulted": 3,
            "documents_supporting": 2,
            "demotion": Demotion.NONE.value,
        },
    )
    card = presentation_for_claim(claim, view)
    assert card.verification_label == "Confirmado"
    assert card.presentation_kind == "confirmed"
    assert "2 procedencias independientes conocidas" in card.coverage
    assert "2 medios respaldan" in card.coverage
    assert "medios" in card.coverage
    assert card.document_noun == "medios"
    assert "corroboración independiente" in (card.explanation or "")


def test_authentic_primary_is_not_weak_single_origin() -> None:
    docs = [_evidence(evidence_type=EvidenceType.SUPPORTS, name="Taquígrafos", url="https://hcdn.gob.ar/v")]
    claim = _claim(status=ClaimStatus.SINGLE_SOURCE, evidence=docs)
    view = _view(
        claim,
        basis={
            "known_independent_count": 1,
            "unknown_group_count": 0,
            "documents_consulted": 1,
            "documents_supporting": 1,
            "statement_evidence_class": StatementEvidenceClass.AUTHENTIC_PRIMARY.value,
            "demotion": Demotion.NONE.value,
        },
    )
    card = presentation_for_claim(claim, view)
    assert card.verification_label == AUTHENTIC_PRIMARY_LABEL
    assert card.presentation_kind == "confirmed_utterance"
    assert not authentic_primary_sounds_weak(card)
    assert "no comprueba el contenido" in (card.explanation or "")
    _assert_safe_single_source(claim, card)


def test_unrelated_official_primary_limitation() -> None:
    docs = [_evidence(evidence_type=EvidenceType.MENTIONS, name="Boletín", url="https://boletinoficial.gob.ar/x")]
    claim = _claim(status=ClaimStatus.SINGLE_SOURCE, evidence=docs)
    view = _view(
        claim,
        basis={
            "known_independent_count": 0,
            "unknown_group_count": 0,
            "documents_consulted": 1,
            "documents_supporting": 0,
            "primary_access": PrimaryAccess.FOUND_UNRELATED.value,
            "demotion": Demotion.MISSING_DOCUMENTARY_PRIMARY.value,
        },
    )
    card = presentation_for_claim(claim, view)
    assert card.limitation == "El documento oficial consultado no sostiene esta proposición."
    assert "ninguno respalda" in card.coverage
    assert card.verification_label == "No confirmado"
    assert card.presentation_kind == "not_confirmed"
    _assert_safe_single_source(claim, card)


def test_mentions_qualify_contradict_consulted_not_supporting() -> None:
    docs = [
        _evidence(evidence_type=EvidenceType.MENTIONS, name="A", url="https://a.test/1"),
        _evidence(evidence_type=EvidenceType.QUALIFIES, name="B", url="https://b.test/2"),
        _evidence(evidence_type=EvidenceType.CONTRADICTS, name="C", url="https://c.test/3"),
    ]
    claim = _claim(status=ClaimStatus.CONFLICTING, evidence=docs)
    view = _view(
        claim,
        basis={
            "known_independent_count": 0,
            "unknown_group_count": 1,
            "documents_consulted": 3,
            "documents_supporting": 0,
            "demotion": Demotion.NONE.value,
        },
    )
    card = presentation_for_claim(claim, view)
    assert "ninguno respalda" in card.coverage
    stances = {row.stance for row in card.evidence_detail}
    assert stances == {"menciona", "matiza", "contradice"}


def test_same_document_several_excerpt_rows_collapse() -> None:
    source_item_id = uuid4()
    item = SimpleNamespace(
        url="https://a.test/n",
        canonical_url="https://a.test/n",
        title="Nota",
        source=SimpleNamespace(name="A", domain="a.test", source_type=None),
    )
    dupes = [
        SimpleNamespace(
            evidence_type=EvidenceType.SUPPORTS,
            source_item_id=source_item_id,
            source_url=item.url,
            source_item=item,
        )
        for _ in range(3)
    ]
    claim = _claim(status=ClaimStatus.SINGLE_SOURCE, evidence=dupes)
    view = _view(
        claim,
        basis={
            "known_independent_count": 1,
            "documents_consulted": 1,
            "documents_supporting": 1,
            "demotion": Demotion.INSUFFICIENT_INDEPENDENCE.value,
        },
    )
    card = presentation_for_claim(claim, view)
    assert len(card.evidence_detail) == 1
    assert "3 evidencias" not in card.coverage


def test_historical_without_support_basis_is_unknown() -> None:
    docs = [
        _evidence(evidence_type=EvidenceType.SUPPORTS, name="A", url="https://a.test/1"),
        _evidence(evidence_type=EvidenceType.SUPPORTS, name="B", url="https://b.test/2"),
    ]
    claim = _claim(status=ClaimStatus.SINGLE_SOURCE, evidence=docs)
    view = VerificationView(
        paired=False,
        sol_by_id={
            str(claim.id): {
                "reason": "varias fuentes independientes confirman",
                "llm_reason": "varias fuentes independientes confirman",
            }
        },
    )
    card = presentation_for_claim(claim, view)
    assert card.basis_known is False
    assert card.coverage == NOT_EVALUATED_COVERAGE
    assert card.documents_consulted is None
    assert card.documents_supporting is None
    assert card.verification_label == NOT_EVALUATED_LABEL
    assert "independencia desconocida" not in card.verification_label.casefold()
    payload = public_presentation_payload(card)
    assert not contains_llm_reason(payload)
    _assert_safe_single_source(claim, card)


def test_boletin_is_document_not_medio() -> None:
    docs = [
        _evidence(
            evidence_type=EvidenceType.SUPPORTS,
            name="Boletín Oficial",
            url="https://www.boletinoficial.gob.ar/n",
            source_type="official",
        )
    ]
    claim = _claim(status=ClaimStatus.SINGLE_SOURCE, evidence=docs)
    view = _view(
        claim,
        basis={
            "known_independent_count": 1,
            "documents_consulted": 1,
            "documents_supporting": 1,
            "demotion": Demotion.INSUFFICIENT_INDEPENDENCE.value,
        },
    )
    card = presentation_for_claim(claim, view)
    assert card.document_noun == "documentos"
    assert "medio" not in card.coverage


def test_skipped_claim_is_not_evaluated_unknown_independence() -> None:
    docs = [_evidence(evidence_type=EvidenceType.SUPPORTS, name="A", url="https://a.test/1")]
    claim = _claim(status=ClaimStatus.SINGLE_SOURCE, evidence=docs)
    view = _view(
        claim,
        basis={},
        evaluation_state="skipped",
        llm_reason="policy_skip",
    )
    card = presentation_for_claim(claim, view)
    payload = public_presentation_payload(card)
    assert card.verification_label == NOT_EVALUATED_LABEL
    assert card.coverage == NOT_EVALUATED_COVERAGE
    assert card.basis_known is False
    assert "independencia desconocida" not in card.verification_label.casefold()
    assert "independencia desconocida" not in (card.coverage or "").casefold()
    assert "policy_skip" not in str(payload)
    blob = " ".join(part for part in (card.verification_label, card.coverage, card.explanation) if part)
    assert "skipped" not in blob.casefold()
    assert card.presentation_kind == "unevaluated_skipped"
    assert not contains_llm_reason(payload)


def test_complete_single_source_keeps_current_copy() -> None:
    docs = [
        _evidence(evidence_type=EvidenceType.SUPPORTS, name="A", url="https://a.test/1"),
        _evidence(evidence_type=EvidenceType.SUPPORTS, name="B", url="https://b.test/2"),
        _evidence(evidence_type=EvidenceType.SUPPORTS, name="C", url="https://c.test/3"),
    ]
    claim = _claim(status=ClaimStatus.SINGLE_SOURCE, evidence=docs)
    view = _view(
        claim,
        basis={
            "known_independent_count": 1,
            "unknown_group_count": 0,
            "reprint_collapsed_count": 2,
            "documents_consulted": 3,
            "documents_supporting": 3,
            "demotion": Demotion.INSUFFICIENT_INDEPENDENCE.value,
        },
        evaluation_state="complete",
    )
    card = presentation_for_claim(claim, view)
    assert card.verification_label == "Respaldo limitado"
    assert card.presentation_kind == "limited_support"
    assert card.basis_known is True
    assert "Se consultaron 3 documentos" in card.coverage
    _assert_safe_single_source(claim, card)


def test_legacy_decision_without_evaluation_state_keeps_evaluated_copy() -> None:
    docs = [
        _evidence(evidence_type=EvidenceType.SUPPORTS, name="A", url="https://a.test/1"),
        _evidence(evidence_type=EvidenceType.SUPPORTS, name="B", url="https://b.test/2"),
        _evidence(evidence_type=EvidenceType.SUPPORTS, name="C", url="https://c.test/3"),
    ]
    claim = _claim(status=ClaimStatus.SINGLE_SOURCE, evidence=docs)
    view = _view(
        claim,
        basis={
            "known_independent_count": 0,
            "unknown_group_count": 2,
            "documents_consulted": 3,
            "documents_supporting": 3,
            "demotion": Demotion.UNPROVEN_INDEPENDENCE.value,
        },
    )
    card = presentation_for_claim(claim, view)
    assert card.verification_label == "Respaldo limitado"
    assert card.presentation_kind == "limited_support"
    assert card.basis_known is True
    _assert_safe_single_source(claim, card)


def test_unpaired_legacy_decision_keeps_unknown_coverage() -> None:
    docs = [_evidence(evidence_type=EvidenceType.SUPPORTS, name="A", url="https://a.test/1")]
    claim = _claim(status=ClaimStatus.SINGLE_SOURCE, evidence=docs)
    cid = str(claim.id)
    view = VerificationView(
        paired=False,
        decision_by_claim_id={
            cid: {
                "claim_id": cid,
                "status": claim.status.value,
                "support_basis": {"known_independent_count": 1, "documents_consulted": 1},
            }
        },
    )
    card = presentation_for_claim(claim, view)
    assert card.verification_label == NOT_EVALUATED_LABEL
    assert card.coverage == UNKNOWN_COVERAGE
    assert card.basis_known is False
    assert card.presentation_kind == "unevaluated"


def test_skip_shaped_legacy_decision_is_not_evaluated_copy() -> None:
    docs = [_evidence(evidence_type=EvidenceType.SUPPORTS, name="A", url="https://a.test/1")]
    claim = _claim(status=ClaimStatus.SINGLE_SOURCE, evidence=docs)
    view = _view(
        claim,
        basis={},
        llm_reason="policy_skip",
    )
    card = presentation_for_claim(claim, view)
    assert card.verification_label == NOT_EVALUATED_LABEL
    assert "independencia desconocida" not in card.verification_label.casefold()


def test_confirmed_factual_requires_sufficient_contract() -> None:
    docs = [
        _evidence(evidence_type=EvidenceType.SUPPORTS, name="A", url="https://a.test/1"),
        _evidence(evidence_type=EvidenceType.SUPPORTS, name="B", url="https://b.test/2"),
    ]
    claim = _claim(status=ClaimStatus.SUPPORTED, evidence=docs)
    view = _view(
        claim,
        basis={
            "known_independent_count": 2,
            "documents_consulted": 2,
            "documents_supporting": 2,
            "kind": "independent_reporting",
            "demotion": Demotion.NONE.value,
        },
        evaluation_state="complete",
        reason_code=ReasonCode.INDEPENDENT_CORROBORATION.value,
        public_rendering={
            "attribution_required": False,
            "categorical_allowed": True,
            "headline_unattributed_allowed": True,
            "independent_confirmation_language_allowed": True,
        },
    )
    card = presentation_for_claim(claim, view)
    assert card.presentation_kind == "confirmed"
    assert card.verification_label == "Confirmado"
    assert "corroboración independiente" in (card.explanation or "")
    assert "3 fuentes" not in (card.explanation or "")
    payload = public_presentation_payload(card)
    assert "demotion" not in payload
    assert not public_copy_has_technical_tokens(card)


def test_supported_without_sufficient_contract_is_not_confirmed() -> None:
    docs = [_evidence(evidence_type=EvidenceType.SUPPORTS, name="A", url="https://a.test/1")]
    claim = _claim(status=ClaimStatus.SUPPORTED, evidence=docs)
    view = _view(
        claim,
        basis={
            "known_independent_count": 1,
            "documents_consulted": 1,
            "documents_supporting": 1,
            "demotion": Demotion.NONE.value,
        },
        evaluation_state="complete",
        reason_code=ReasonCode.INSUFFICIENT_EVIDENCE.value,
    )
    card = presentation_for_claim(claim, view)
    assert card.verification_label != "Confirmado"
    assert card.presentation_kind == "limited_support"


def test_confirmed_utterance_keeps_speaker_and_does_not_confirm_content() -> None:
    docs = [
        _evidence(evidence_type=EvidenceType.SUPPORTS, name="Taquígrafos", url="https://hcdn.gob.ar/v"),
        _evidence(evidence_type=EvidenceType.SUPPORTS, name="Canal", url="https://tv.test/v"),
    ]
    claim = _claim(
        status=ClaimStatus.SUPPORTED,
        evidence=docs,
        claim_type="declaracion",
        subject="Pérez",
        canonical_text="Pérez afirmó que el costo será de 40.000 millones",
    )
    view = _view(
        claim,
        basis={
            "known_independent_count": 2,
            "documents_consulted": 2,
            "documents_supporting": 2,
            "statement_evidence_class": StatementEvidenceClass.AUTHENTIC_PRIMARY.value,
            "kind": "primary_source",
            "demotion": Demotion.NONE.value,
        },
        evaluation_state="complete",
        reason_code=ReasonCode.PRIMARY_AUTHENTIC_UTTERANCE.value,
        proposition_role=PropositionRole.UTTERANCE.value,
    )
    card = presentation_for_claim(claim, view)
    assert card.presentation_kind == "confirmed_utterance"
    assert card.verification_label == "Declaración confirmada"
    assert "Pérez" in (card.explanation or "")
    assert "no comprueba el contenido" in (card.explanation or "")
    assert "reacción" in (card.explanation or "")
    assert card.verification_label != "Confirmado"


def test_single_source_without_admitted_support_does_not_invent_backing() -> None:
    claim = _claim(status=ClaimStatus.SINGLE_SOURCE, evidence=[])
    view = _view(
        claim,
        basis={
            "known_independent_count": 0,
            "documents_consulted": 1,
            "documents_supporting": 0,
            "demotion": Demotion.NONE.value,
        },
        evaluation_state="complete",
    )
    card = presentation_for_claim(claim, view)
    assert card.presentation_kind == "not_confirmed"
    assert card.verification_label == "No confirmado"
    assert "respaldo admitido" not in (card.explanation or "").casefold()
    assert "un origen informativo" not in (card.explanation or "").casefold()
    assert "no equivale a desmentirla" in (card.explanation or "")


def test_partial_support_with_and_without_fragment() -> None:
    docs = [_evidence(evidence_type=EvidenceType.QUALIFIES, name="A", url="https://a.test/1")]
    claim = _claim(
        status=ClaimStatus.SINGLE_SOURCE,
        evidence=docs,
        canonical_text="El decreto elimina el régimen y entra en vigencia mañana",
    )
    with_fragment = _view(
        claim,
        basis={
            "known_independent_count": 1,
            "documents_consulted": 1,
            "documents_supporting": 0,
            "documents_qualifying": 1,
            "demotion": Demotion.PARTIAL_SUPPORT.value,
            "evaluated_canonical_text": claim.canonical_text,
        },
        evaluation_state="complete",
        reason_code=ReasonCode.PARTIAL_SUPPORT.value,
        verified_scope="El decreto elimina el régimen",
    )
    card = presentation_for_claim(claim, with_fragment)
    assert card.presentation_kind == "limited_support"
    assert "El decreto elimina el régimen" in (card.explanation or "")
    assert "entra en vigencia mañana" not in (card.explanation or "")
    assert "falso" in (card.explanation or "")
    without = _view(
        claim,
        basis={
            "known_independent_count": 1,
            "documents_consulted": 1,
            "documents_supporting": 0,
            "documents_qualifying": 1,
            "demotion": Demotion.PARTIAL_SUPPORT.value,
        },
        evaluation_state="complete",
        reason_code=ReasonCode.PARTIAL_SUPPORT.value,
    )
    bare = presentation_for_claim(claim, without)
    assert "fragmento" in (bare.explanation or "")
    assert "El decreto elimina el régimen y entra en vigencia mañana" not in (bare.explanation or "").replace(claim.canonical_text, "")


def test_conflicting_and_disproven_vocabulary() -> None:
    docs = [
        _evidence(evidence_type=EvidenceType.SUPPORTS, name="A", url="https://a.test/1"),
        _evidence(evidence_type=EvidenceType.CONTRADICTS, name="B", url="https://b.test/2"),
    ]
    conflicting = _claim(status=ClaimStatus.CONFLICTING, evidence=docs)
    card = presentation_for_claim(
        conflicting,
        _view(
            conflicting,
            basis={"known_independent_count": 1, "documents_consulted": 2, "documents_supporting": 1},
            evaluation_state="complete",
            reason_code=ReasonCode.CONFLICTING_COMPARABLE_EVIDENCE.value,
        ),
    )
    assert card.presentation_kind == "disputed"
    assert card.verification_label == "En disputa"
    assert "mentira" not in (card.explanation or "").casefold()
    disproven = _claim(status=ClaimStatus.DISPROVEN, evidence=docs)
    contradicho = presentation_for_claim(
        disproven,
        _view(
            disproven,
            basis={"known_independent_count": 1, "documents_consulted": 2, "documents_supporting": 0},
            evaluation_state="complete",
            reason_code=ReasonCode.COMPARABLE_DISPROOF.value,
        ),
    )
    assert contradicho.presentation_kind == "disproven"
    assert contradicho.verification_label == "Contradicho"
    assert "engañar" in (contradicho.explanation or "")


def test_pending_failed_and_unknown_are_not_not_confirmed() -> None:
    docs = [_evidence(evidence_type=EvidenceType.SUPPORTS, name="A", url="https://a.test/1")]
    claim = _claim(status=ClaimStatus.SINGLE_SOURCE, evidence=docs)
    pending = presentation_for_claim(claim, _view(claim, basis={}, evaluation_state="pending"))
    assert pending.verification_label == "Verificación pendiente"
    assert pending.presentation_kind == "unevaluated_pending"
    assert pending.verification_label != "No confirmado"
    failed = presentation_for_claim(claim, _view(claim, basis={}, evaluation_state="failed"))
    assert failed.verification_label == "Verificación no completada"
    assert failed.presentation_kind == "unevaluated_failed"
    assert failed.verification_label != "No confirmado"
    unknown = presentation_for_claim(claim, VerificationView(paired=True))
    assert unknown.verification_label == NOT_EVALUATED_LABEL
    assert unknown.presentation_kind == "unevaluated"


def test_full_verified_scope_is_not_enough_for_confirmed() -> None:
    text = "Hubo un incendio en el depósito de Rosario"
    docs = [_evidence(evidence_type=EvidenceType.SUPPORTS, name="A", url="https://a.test/1")]
    claim = _claim(status=ClaimStatus.SINGLE_SOURCE, evidence=docs, canonical_text=text)
    card = presentation_for_claim(
        claim,
        _view(
            claim,
            basis={
                "known_independent_count": 1,
                "documents_consulted": 1,
                "documents_supporting": 1,
                "demotion": Demotion.INSUFFICIENT_INDEPENDENCE.value,
                "evaluated_canonical_text": text,
            },
            evaluation_state="complete",
            verified_scope=text,
        ),
    )
    assert card.verification_label == "Respaldo limitado"
    assert card.presentation_kind != "confirmed"


def test_admin_payload_keeps_demotion_public_payload_drops_it() -> None:
    docs = [_evidence(evidence_type=EvidenceType.SUPPORTS, name="A", url="https://a.test/1")]
    claim = _claim(status=ClaimStatus.SINGLE_SOURCE, evidence=docs)
    card = presentation_for_claim(
        claim,
        _view(
            claim,
            basis={
                "known_independent_count": 1,
                "documents_consulted": 1,
                "documents_supporting": 1,
                "demotion": Demotion.INSUFFICIENT_INDEPENDENCE.value,
            },
            evaluation_state="complete",
        ),
    )
    public = public_presentation_payload(card)
    admin = public_presentation_payload(card, include_internal=True)
    assert "demotion" not in public
    assert admin["demotion"] == Demotion.INSUFFICIENT_INDEPENDENCE.value
    assert public["documents_supporting"] == 1
    assert "documents_reporting" not in public


@pytest.mark.parametrize(
    "case",
    [
        {
            "id": "confirmed_factual",
            "status": ClaimStatus.SUPPORTED,
            "basis": {
                "known_independent_count": 2,
                "documents_consulted": 2,
                "documents_supporting": 2,
                "kind": "independent_reporting",
                "demotion": Demotion.NONE.value,
            },
            "evaluation_state": "complete",
            "reason_code": ReasonCode.INDEPENDENT_CORROBORATION.value,
            "public_rendering": {
                "attribution_required": False,
                "categorical_allowed": True,
                "headline_unattributed_allowed": True,
                "independent_confirmation_language_allowed": True,
            },
            "label": "Confirmado",
            "kind": "confirmed",
            "explanation_has": ["corroboración independiente"],
            "explanation_not": ["3 fuentes", "SINGLE_SOURCE"],
        },
        {
            "id": "confirmed_utterance",
            "status": ClaimStatus.SUPPORTED,
            "claim_type": "declaracion",
            "subject": "Pérez",
            "canonical_text": "Pérez afirmó que el costo será de 40.000 millones",
            "basis": {
                "known_independent_count": 2,
                "documents_consulted": 2,
                "documents_supporting": 2,
                "statement_evidence_class": StatementEvidenceClass.AUTHENTIC_PRIMARY.value,
                "kind": "primary_source",
                "demotion": Demotion.NONE.value,
            },
            "evaluation_state": "complete",
            "reason_code": ReasonCode.PRIMARY_AUTHENTIC_UTTERANCE.value,
            "proposition_role": PropositionRole.UTTERANCE.value,
            "label": "Declaración confirmada",
            "kind": "confirmed_utterance",
            "explanation_has": ["Pérez", "no comprueba el contenido"],
            "explanation_not": ["Confirmado el costo", "reacción adicional quedó"],
        },
        {
            "id": "single_source_with_support",
            "status": ClaimStatus.SINGLE_SOURCE,
            "basis": {
                "known_independent_count": 1,
                "documents_consulted": 1,
                "documents_supporting": 1,
                "demotion": Demotion.INSUFFICIENT_INDEPENDENCE.value,
            },
            "evaluation_state": "complete",
            "reason_code": ReasonCode.SINGLE_KNOWN_ORIGIN.value,
            "label": "Respaldo limitado",
            "kind": "limited_support",
            "explanation_has": ["respaldo admitido"],
            "explanation_not": ["corroboración independiente suficiente para presentar la proposición completa como confirmada"],
        },
        {
            "id": "single_source_without_support",
            "status": ClaimStatus.SINGLE_SOURCE,
            "evidence": False,
            "basis": {
                "known_independent_count": 0,
                "documents_consulted": 1,
                "documents_supporting": 0,
                "demotion": Demotion.NONE.value,
            },
            "evaluation_state": "complete",
            "label": "No confirmado",
            "kind": "not_confirmed",
            "explanation_has": ["no equivale a desmentirla"],
            "explanation_not": ["Hay respaldo admitido"],
        },
        {
            "id": "disputed",
            "status": ClaimStatus.CONFLICTING,
            "basis": {"known_independent_count": 1, "documents_consulted": 2, "documents_supporting": 1},
            "evaluation_state": "complete",
            "reason_code": ReasonCode.CONFLICTING_COMPARABLE_EVIDENCE.value,
            "label": "En disputa",
            "kind": "disputed",
            "explanation_has": ["versiones comparables"],
            "explanation_not": ["mentira", "engañar"],
        },
        {
            "id": "disproven",
            "status": ClaimStatus.DISPROVEN,
            "basis": {"known_independent_count": 1, "documents_consulted": 2, "documents_supporting": 0},
            "evaluation_state": "complete",
            "reason_code": ReasonCode.COMPARABLE_DISPROOF.value,
            "label": "Contradicho",
            "kind": "disproven",
            "explanation_has": ["desmiente", "no atribuye mentira"],
            "explanation_not": ["SINGLE_SOURCE"],
        },
        {
            "id": "skipped",
            "status": ClaimStatus.SINGLE_SOURCE,
            "basis": {},
            "evaluation_state": "skipped",
            "label": NOT_EVALUATED_LABEL,
            "kind": "unevaluated_skipped",
            "explanation_has": ["no se evaluó"],
            "explanation_not": ["desmentirla", "nunca se intentó"],
        },
        {
            "id": "pending",
            "status": ClaimStatus.SINGLE_SOURCE,
            "basis": {},
            "evaluation_state": "pending",
            "label": "Verificación pendiente",
            "kind": "unevaluated_pending",
            "explanation_has": ["aún no está disponible"],
            "explanation_not": ["desmentirla"],
        },
        {
            "id": "failed",
            "status": ClaimStatus.SINGLE_SOURCE,
            "basis": {},
            "evaluation_state": "failed",
            "label": "Verificación no completada",
            "kind": "unevaluated_failed",
            "explanation_has": ["no llegó a un resultado utilizable"],
            "explanation_not": ["desmentirla"],
        },
        {
            "id": "unknown",
            "status": ClaimStatus.SINGLE_SOURCE,
            "basis": None,
            "label": NOT_EVALUATED_LABEL,
            "kind": "unevaluated",
            "explanation_has": ["No hay información suficiente"],
            "explanation_not": ["nunca se intentó", "falló"],
        },
    ],
)
def test_c9_presentation_example_table(case: dict) -> None:
    evidence = [] if case.get("evidence") is False else [_evidence(evidence_type=EvidenceType.SUPPORTS, name="A", url="https://a.test/1")]
    claim = _claim(
        status=case["status"],
        evidence=evidence,
        claim_type=case.get("claim_type", "hecho"),
        subject=case.get("subject"),
        canonical_text=case.get("canonical_text", "La afirmación"),
    )
    if case.get("basis") is None:
        view = VerificationView(paired=True)
    else:
        view = _view(
            claim,
            basis=case["basis"],
            evaluation_state=case.get("evaluation_state"),
            reason_code=case.get("reason_code"),
            proposition_role=case.get("proposition_role"),
            public_rendering=case.get("public_rendering"),
        )
    card = presentation_for_claim(claim, view)
    assert card.verification_label == case["label"]
    assert card.presentation_kind == case["kind"]
    text = card.explanation or ""
    for snippet in case["explanation_has"]:
        assert snippet.casefold() in text.casefold()
    for snippet in case["explanation_not"]:
        assert snippet.casefold() not in text.casefold()
    assert not public_copy_has_technical_tokens(card)


def test_counts_unknown_are_not_zero_and_stay_out_of_certainty_label() -> None:
    claim = _claim(status=ClaimStatus.SINGLE_SOURCE, evidence=[])
    card = presentation_for_claim(claim, VerificationView(paired=True))
    payload = public_presentation_payload(card)
    assert payload["documents_consulted"] is None
    assert payload["documents_supporting"] is None
    assert payload["known_independent_count"] is None
    assert payload["unknown_group_count"] is None
    assert payload["verification_label"] == NOT_EVALUATED_LABEL
    assert "0 documento" not in (card.coverage or "")
    assert "Confirmado" not in (card.verification_label)

