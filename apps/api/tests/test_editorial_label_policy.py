from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy.orm import Session

from app.domain.enums import ClaimStatus, EditorialLabel, EvidenceType
from app.services.editorial_label_policy import labels_for_event_claims
from app.services.verification_outcome import VerificationView


def _claim(**overrides):
    payload = {
        "id": uuid4(),
        "canonical_text": "El hecho ocurrió",
        "status": ClaimStatus.SUPPORTED,
        "subject": "decreto",
        "predicate": "elimina",
        "object_text": "X",
        "normalized_value": "si",
        "unit": None,
        "occurred_at": None,
        "evidence": [],
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def _evidence(*, evidence_type: EvidenceType, excerpt: str | None, source_name: str = "Medio", url: str = "https://medio.test/n"):
    source_item_id = uuid4()
    return SimpleNamespace(
        evidence_type=evidence_type,
        excerpt=excerpt,
        source_item_id=source_item_id,
        source_url=url,
        source_item=SimpleNamespace(
            url=url,
            source=SimpleNamespace(name=source_name, domain="medio.test"),
        ),
    )


def _view_for(claim, *, primary: bool = True, skipped: bool = False, unresolved: bool = False, selected: bool = True) -> VerificationView:
    cid = str(claim.id)
    return VerificationView(
        selected_ids={cid} if selected else set(),
        skipped_search={cid} if skipped else set(),
        primary_source_supports={cid: primary},
        sol_by_id={
            cid: {
                "claim_id": cid,
                "status_after": claim.status.value,
                "unresolved": unresolved,
            }
        },
    )


def _labels(claim, mapping):
    return [label.value for label in mapping[str(claim.id)].labels]


def test_case_a_two_supports_without_verification() -> None:
    a = _evidence(evidence_type=EvidenceType.SUPPORTS, excerpt="confirma", source_name="A", url="https://a.test/n")
    b = _evidence(evidence_type=EvidenceType.SUPPORTS, excerpt="confirma", source_name="B", url="https://b.test/n")
    claim = _claim(evidence=[a, b])
    mapping = labels_for_event_claims([claim], VerificationView())
    assert _labels(claim, mapping) == []
    assert mapping[str(claim.id)].false_assertions == []


def test_case_b_checked_requires_real_verification() -> None:
    a = _evidence(evidence_type=EvidenceType.SUPPORTS, excerpt="confirma", source_name="A")
    b = _evidence(evidence_type=EvidenceType.SUPPORTS, excerpt="confirma", source_name="B")
    claim = _claim(status=ClaimStatus.SUPPORTED, evidence=[a, b])
    mapping = labels_for_event_claims([claim], _view_for(claim, primary=True))
    assert _labels(claim, mapping) == [EditorialLabel.CHECKED.value]


def test_preferred_url_without_primary_flag_is_not_checked() -> None:
    official = _evidence(
        evidence_type=EvidenceType.SUPPORTS,
        excerpt="boletin",
        source_name="Boletín",
        url="https://www.boletinoficial.gob.ar/detalle/1",
    )
    claim = _claim(evidence=[official])
    mapping = labels_for_event_claims([claim], _view_for(claim, primary=False))
    assert EditorialLabel.CHECKED.value not in _labels(claim, mapping)


def test_skipped_search_is_not_checked() -> None:
    claim = _claim(evidence=[_evidence(evidence_type=EvidenceType.SUPPORTS, excerpt="ok")])
    mapping = labels_for_event_claims([claim], _view_for(claim, skipped=True, primary=True))
    assert _labels(claim, mapping) == []


def test_case_c_resolved_discrepancy() -> None:
    winner_ev = _evidence(evidence_type=EvidenceType.SUPPORTS, excerpt="no elimina", source_name="Página/12")
    loser_ev = _evidence(
        evidence_type=EvidenceType.SUPPORTS,
        excerpt="El decreto elimina X",
        source_name="Derecha Diario",
        url="https://derecha.test/n",
    )
    winner = _claim(
        status=ClaimStatus.SUPPORTED,
        object_text="no X",
        normalized_value="no",
        canonical_text="El decreto no elimina X",
        evidence=[winner_ev],
    )
    loser = _claim(
        status=ClaimStatus.DISPROVEN,
        object_text="X",
        normalized_value="si",
        canonical_text="El decreto elimina X",
        evidence=[loser_ev],
    )
    view = _view_for(winner, primary=True)
    mapping = labels_for_event_claims([winner, loser], view)
    assert _labels(winner, mapping) == [EditorialLabel.CHECKED.value, EditorialLabel.DISCREPANCY.value]
    assert _labels(loser, mapping) == [EditorialLabel.DISCREPANCY.value, EditorialLabel.FALSE_CLAIM.value]
    assert mapping[str(winner.id)].false_assertions == [
        {
            "source_item_id": str(loser_ev.source_item_id),
            "source_name": "Derecha Diario",
            "source_url": "https://derecha.test/n",
            "excerpt": "El decreto elimina X",
        }
    ]
    assert mapping[str(loser.id)].false_assertions == []


def test_case_d_disputed_when_unresolved() -> None:
    supports = _evidence(evidence_type=EvidenceType.SUPPORTS, excerpt="si")
    contradicts = _evidence(evidence_type=EvidenceType.CONTRADICTS, excerpt="no")
    claim = _claim(status=ClaimStatus.CONFLICTING, evidence=[supports, contradicts])
    view = _view_for(claim, unresolved=True, primary=False)
    mapping = labels_for_event_claims([claim], view)
    assert _labels(claim, mapping) == [EditorialLabel.DISCREPANCY.value, EditorialLabel.DISPUTED.value]


def test_contradicts_without_disproven_sibling_is_not_false_claim() -> None:
    supports = _evidence(evidence_type=EvidenceType.SUPPORTS, excerpt="si")
    contradicts = _evidence(evidence_type=EvidenceType.CONTRADICTS, excerpt="no")
    claim = _claim(status=ClaimStatus.SUPPORTED, evidence=[supports, contradicts])
    mapping = labels_for_event_claims([claim], _view_for(claim, primary=True))
    assert _labels(claim, mapping) == [EditorialLabel.CHECKED.value, EditorialLabel.DISCREPANCY.value]
    assert mapping[str(claim.id)].false_assertions == []


def test_qualifies_does_not_create_discrepancy() -> None:
    supports = _evidence(evidence_type=EvidenceType.SUPPORTS, excerpt="si")
    qualifies = _evidence(evidence_type=EvidenceType.QUALIFIES, excerpt="en parte")
    claim = _claim(status=ClaimStatus.SINGLE_SOURCE, evidence=[supports, qualifies])
    mapping = labels_for_event_claims([claim], VerificationView())
    assert _labels(claim, mapping) == []


def test_case_f_temporal_update_is_not_false_or_discrepancy() -> None:
    from datetime import datetime, timezone

    at_10 = datetime(2026, 8, 24, 10, 0, tzinfo=timezone.utc)
    at_14 = datetime(2026, 8, 24, 14, 0, tzinfo=timezone.utc)
    earlier = _claim(
        status=ClaimStatus.OUTDATED,
        normalized_value="3",
        object_text="3",
        subject="accidente",
        predicate="cantidad_heridos",
        unit="personas",
        occurred_at=at_10,
        canonical_text="Hay 3 heridos",
        evidence=[_evidence(evidence_type=EvidenceType.SUPPORTS, excerpt="3 heridos")],
    )
    later = _claim(
        status=ClaimStatus.SINGLE_SOURCE,
        normalized_value="5",
        object_text="5",
        subject="accidente",
        predicate="cantidad_heridos",
        unit="personas",
        occurred_at=at_14,
        canonical_text="Hay 5 heridos",
        evidence=[_evidence(evidence_type=EvidenceType.SUPPORTS, excerpt="5 heridos")],
    )
    mapping = labels_for_event_claims([earlier, later], VerificationView())
    assert _labels(earlier, mapping) == []
    assert _labels(later, mapping) == []
    assert mapping[str(later.id)].false_assertions == []


def test_compact_public_claims_includes_editorial_payload(db_session: Session) -> None:
    from app.domain.enums import ClaimImportance, IngestionMethod
    from app.models import Claim, ClaimEvidence, PipelineRun
    from app.schemas import EventCreate, SourceCreate, SourceItemCreate
    from app.services.event_service import EventService
    from app.services.feed_ranking import compact_public_claims
    from app.services.source_item_service import SourceItemService
    from app.services.source_service import SourceService
    from app.services.verification_service import VERIFICATION_STAGE
    from app.domain.enums import PipelineStatus

    source = SourceService(db_session).create(
        SourceCreate(
            name="Oficial",
            preferred_ingestion_method=IngestionMethod.RSS,
            feed_url="https://oficial.test/rss.xml",
            is_monitored=True,
            is_enabled=True,
            domain="oficial.test",
        )
    )
    item = SourceItemService(db_session).ingest(
        SourceItemCreate(
            source_id=source.id,
            url="https://oficial.test/n",
            canonical_url="https://oficial.test/n",
            content_hash="ed1",
            title="Decreto",
            clean_text="El decreto no elimina X",
        )
    ).item
    event = EventService(db_session).create(
        EventCreate(
            title_internal="Decreto",
            event_type="anuncio_oficial",
            source_item_id=item.id,
            started_at=datetime.now(timezone.utc),
            locality="CABA",
            province="CABA",
            short_summary="Decreto",
        )
    )
    claim = Claim(
        event_id=event.id,
        canonical_text="El decreto no elimina X",
        claim_type="documento",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.SUPPORTED,
        subject="decreto",
        predicate="elimina",
        object_text="no X",
        normalized_value="no",
    )
    db_session.add(claim)
    db_session.flush()
    db_session.add(
        ClaimEvidence(
            claim_id=claim.id,
            source_item_id=item.id,
            evidence_type=EvidenceType.SUPPORTS,
            excerpt="El decreto no elimina X",
            source_url=item.url,
        )
    )
    cid = str(claim.id)
    db_session.add(
        PipelineRun(
            event_id=event.id,
            stage=VERIFICATION_STAGE,
            status=PipelineStatus.SUCCESS,
            finished_at=datetime.now(timezone.utc),
            metadata_json={
                "selected": [{"claim_id": cid, "reasons": ["policy:documento"]}],
                "skipped_search": [],
                "primary_source_supports_claim": {cid: True},
                "sol": [{"claim_id": cid, "status_after": "SUPPORTED", "unresolved": False, "reason": "primaria"}],
            },
        )
    )
    db_session.flush()
    rows = compact_public_claims(db_session, event)
    assert rows[0]["editorial_labels"] == ["CHECKED"]
    assert rows[0]["false_assertions"] == []
