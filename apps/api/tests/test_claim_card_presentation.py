from types import SimpleNamespace
from uuid import uuid4

from app.domain.enums import ClaimStatus, EvidenceType
from app.schemas.editorial_evidence import Demotion, PrimaryAccess, StatementEvidenceClass
from app.services.claim_card_presentation import (
    AUTHENTIC_PRIMARY_LABEL,
    UNKNOWN_COVERAGE,
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


def _view(claim, *, basis: dict, unresolved: bool = False, llm_reason: str | None = None) -> VerificationView:
    cid = str(claim.id)
    decision = {
        "claim_id": cid,
        "status": claim.status.value,
        "unresolved": unresolved,
        "llm_reason": llm_reason,
        "support_basis": basis,
    }
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
    assert card.verification_label == "Un solo origen"
    assert card.basis_known is True
    assert "Se consultaron 3 documentos" in card.coverage
    assert "3 reportan" in card.coverage
    assert card.explanation == "Se basan en la misma información original."
    assert "3 fuentes" not in card.coverage
    assert len(card.evidence_detail) == 3
    _assert_safe_single_source(claim, card)
    payload = public_presentation_payload(card)
    assert "llm_reason" not in payload
    assert payload["documents_consulted"] == 3
    assert payload["documents_reporting"] == 3


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
    assert card.verification_label == "Sin corroboración independiente"
    assert "Se consultaron 3 documentos" in card.coverage
    assert card.explanation == "No se pudo establecer que aporten confirmaciones independientes."
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
    assert card.verification_label == "Corroborado"
    assert "2 orígenes independientes respaldan esta afirmación." in card.coverage
    assert "2 reportan" in card.coverage
    assert "medios" in card.coverage
    assert card.document_noun == "medios"


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
    assert not authentic_primary_sounds_weak(card)
    assert card.explanation is None
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
    assert card.limitation == "El documento oficial no sostiene esta proposición."
    assert "ninguno respalda" in card.coverage
    assert card.verification_label != "Corroborado"
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
    assert card.coverage == UNKNOWN_COVERAGE
    assert card.documents_consulted is None
    assert card.documents_reporting is None
    assert card.verification_label == "Independencia desconocida"
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
