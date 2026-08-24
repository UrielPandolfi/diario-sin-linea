from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.domain.enums import (
    ClaimImportance,
    ClaimStatus,
    EventSourceRelation,
    EventStatus,
    EvidenceType,
    IngestionMethod,
    PipelineStatus,
)
from app.main import app
from app.models import Claim, ClaimEvidence, EventSource, PipelineRun
from app.providers.fakes import FakeStructuredLLM
from app.schemas import EventCreate, SourceCreate, SourceItemCreate
from app.schemas.claims import (
    ClaimExtractionBatch,
    ClaimResolutionBatch,
    ClaimResolutionItem,
    ExtractedClaim,
    ExtractedEvidence,
)
from app.services.claim_service import CLAIM_STAGE, ClaimService
from app.services.event_service import EventService
from app.services.source_item_service import SourceItemService
from app.services.source_service import SourceService


def _source(session: Session, **overrides):
    payload = {
        "name": "Fuente",
        "preferred_ingestion_method": IngestionMethod.RSS,
        "feed_url": "https://www.ejemplo.test/rss.xml",
        "is_monitored": True,
        "is_enabled": True,
        "domain": "ejemplo.test",
    }
    payload.update(overrides)
    return SourceService(session).create(SourceCreate(**payload))


def _item(session: Session, source_id, *, url: str, title: str, body: str, content_hash: str):
    return SourceItemService(session).ingest(
        SourceItemCreate(
            source_id=source_id,
            url=url,
            canonical_url=url,
            content_hash=content_hash,
            title=title,
            clean_text=body,
        )
    ).item


def _event(session: Session, item, **overrides):
    payload = {
        "title_internal": "Choque en Rosario",
        "event_type": "accidente",
        "source_item_id": item.id,
        "started_at": datetime.now(timezone.utc),
        "locality": "Rosario",
        "province": "Santa Fe",
        "short_summary": "Un colectivo chocó en Rosario",
    }
    payload.update(overrides)
    return EventService(session).create(EventCreate(**payload))


def _attach(session: Session, event, item) -> None:
    EventService(session).attach_source(event, item.id, relation_type=EventSourceRelation.ADDITIONAL)


def _extracted(
    *,
    text: str,
    evidence: list[ExtractedEvidence],
    subject: str | None = "accidente",
    predicate: str | None = "hecho",
    object_text: str | None = None,
    normalized_value: str | None = None,
    unit: str | None = None,
) -> ExtractedClaim:
    return ExtractedClaim(
        canonical_text=text,
        claim_type="hecho",
        importance=ClaimImportance.HIGH,
        subject=subject,
        predicate=predicate,
        object_text=object_text or text,
        normalized_value=normalized_value,
        unit=unit,
        evidence=evidence,
    )


def _llm(extraction: ClaimExtractionBatch, resolution: ClaimResolutionBatch | None = None) -> FakeStructuredLLM:
    responses: dict = {"ClaimExtractionBatch": extraction}
    if resolution is not None:
        responses["ClaimResolutionBatch"] = resolution
    return FakeStructuredLLM(responses)


def _service(session: Session, llm: FakeStructuredLLM) -> ClaimService:
    return ClaimService(session, extractor_llm=llm, resolver_llm=llm)


def _event_claims(session: Session, event_id) -> list[Claim]:
    return list(session.scalars(select(Claim).where(Claim.event_id == event_id)))


def test_single_source_supports(db_session: Session) -> None:
    source = _source(db_session)
    body = "El choque dejó seis heridos en Rosario."
    item = _item(
        db_session, source.id, url="https://ejemplo.test/choque", title="Choque", body=body, content_hash="h1"
    )
    event = _event(db_session, item)
    llm = _llm(
        ClaimExtractionBatch(
            claims=[
                _extracted(
                    text="El choque dejó seis heridos",
                    normalized_value="6",
                    unit="personas",
                    predicate="cantidad_heridos",
                    evidence=[
                        ExtractedEvidence(
                            source_ref=1,
                            evidence_type=EvidenceType.SUPPORTS,
                            excerpt="seis heridos",
                            confidence=0.9,
                        )
                    ],
                )
            ]
        ),
        ClaimResolutionBatch(
            items=[
                ClaimResolutionItem(
                    claim_ref=1, status=ClaimStatus.SUPPORTED, confidence=0.9, reason="una fuente"
                )
            ]
        ),
    )

    result = _service(db_session, llm).resolve(event.id, trigger="admin")

    assert result["skipped"] is False
    assert result["persisted"] == 1
    claims = _event_claims(db_session, event.id)
    assert len(claims) == 1
    assert claims[0].status == ClaimStatus.SINGLE_SOURCE
    evidence = list(db_session.scalars(select(ClaimEvidence).where(ClaimEvidence.claim_id == claims[0].id)))
    assert evidence[0].source_item_id == item.id
    assert evidence[0].evidence_type == EvidenceType.SUPPORTS


def test_supported_two_distinct_domains(db_session: Session) -> None:
    source_a = _source(db_session, name="A", domain="a.test", feed_url="https://a.test/rss.xml")
    source_b = _source(db_session, name="B", domain="b.test", feed_url="https://b.test/rss.xml")
    body = "El choque dejó seis heridos."
    item_a = _item(db_session, source_a.id, url="https://a.test/n", title="A", body=body, content_hash="ha")
    item_b = _item(db_session, source_b.id, url="https://b.test/n", title="B", body=body, content_hash="hb")
    event = _event(db_session, item_a)
    _attach(db_session, event, item_b)
    llm = _llm(
        ClaimExtractionBatch(
            claims=[
                _extracted(
                    text="El choque dejó seis heridos",
                    normalized_value="6",
                    unit="personas",
                    predicate="cantidad_heridos",
                    evidence=[
                        ExtractedEvidence(
                            source_ref=1, evidence_type=EvidenceType.SUPPORTS, excerpt="seis heridos", confidence=0.9
                        ),
                        ExtractedEvidence(
                            source_ref=2, evidence_type=EvidenceType.SUPPORTS, excerpt="seis heridos", confidence=0.8
                        ),
                    ],
                )
            ]
        ),
        ClaimResolutionBatch(
            items=[
                ClaimResolutionItem(claim_ref=1, status=ClaimStatus.SUPPORTED, confidence=0.9, reason="dos medios")
            ]
        ),
    )

    _service(db_session, llm).resolve(event.id, trigger="admin")

    claim = _event_claims(db_session, event.id)[0]
    assert claim.status == ClaimStatus.SUPPORTED
    ids = {row.source_item_id for row in db_session.scalars(select(ClaimEvidence).where(ClaimEvidence.claim_id == claim.id))}
    assert ids == {item_a.id, item_b.id}


def test_same_outlet_two_items_is_single_source(db_session: Session) -> None:
    source = _source(db_session, domain="medio.test", feed_url="https://medio.test/rss.xml")
    body = "El choque dejó seis heridos."
    item_a = _item(db_session, source.id, url="https://medio.test/a", title="A", body=body, content_hash="ha")
    item_b = _item(db_session, source.id, url="https://medio.test/b", title="B", body=body, content_hash="hb")
    event = _event(db_session, item_a)
    _attach(db_session, event, item_b)
    llm = _llm(
        ClaimExtractionBatch(
            claims=[
                _extracted(
                    text="El choque dejó seis heridos",
                    normalized_value="6",
                    unit="personas",
                    predicate="cantidad_heridos",
                    evidence=[
                        ExtractedEvidence(
                            source_ref=1, evidence_type=EvidenceType.SUPPORTS, excerpt="seis heridos", confidence=0.9
                        ),
                        ExtractedEvidence(
                            source_ref=2, evidence_type=EvidenceType.SUPPORTS, excerpt="seis heridos", confidence=0.8
                        ),
                    ],
                )
            ]
        ),
        ClaimResolutionBatch(
            items=[
                ClaimResolutionItem(claim_ref=1, status=ClaimStatus.SUPPORTED, confidence=0.9, reason="mismo medio")
            ]
        ),
    )

    _service(db_session, llm).resolve(event.id, trigger="admin")

    assert _event_claims(db_session, event.id)[0].status == ClaimStatus.SINGLE_SOURCE


def test_conflicting_supports_and_contradicts(db_session: Session) -> None:
    source_a = _source(db_session, name="A", domain="a.test", feed_url="https://a.test/rss.xml")
    source_b = _source(db_session, name="B", domain="b.test", feed_url="https://b.test/rss.xml")
    item_a = _item(
        db_session,
        source_a.id,
        url="https://a.test/n",
        title="A",
        body="La policía confirmó seis heridos.",
        content_hash="ha",
    )
    item_b = _item(
        db_session,
        source_b.id,
        url="https://b.test/n",
        title="B",
        body="Fuentes oficiales desmintieron que hubiera heridos.",
        content_hash="hb",
    )
    event = _event(db_session, item_a)
    _attach(db_session, event, item_b)
    llm = _llm(
        ClaimExtractionBatch(
            claims=[
                _extracted(
                    text="Hubo seis heridos",
                    normalized_value="6",
                    unit="personas",
                    predicate="cantidad_heridos",
                    evidence=[
                        ExtractedEvidence(
                            source_ref=1,
                            evidence_type=EvidenceType.SUPPORTS,
                            excerpt="seis heridos",
                            confidence=0.9,
                        ),
                        ExtractedEvidence(
                            source_ref=2,
                            evidence_type=EvidenceType.CONTRADICTS,
                            excerpt="desmintieron que hubiera heridos",
                            confidence=0.8,
                        ),
                    ],
                )
            ]
        ),
        ClaimResolutionBatch(
            items=[ClaimResolutionItem(claim_ref=1, status=ClaimStatus.SUPPORTED, confidence=0.5, reason="mezcla")]
        ),
    )

    _service(db_session, llm).resolve(event.id, trigger="admin")

    assert _event_claims(db_session, event.id)[0].status == ClaimStatus.CONFLICTING


def test_conflicting_competing_values(db_session: Session) -> None:
    source_a = _source(db_session, name="A", domain="a.test", feed_url="https://a.test/rss.xml")
    source_b = _source(db_session, name="B", domain="b.test", feed_url="https://b.test/rss.xml")
    item_a = _item(
        db_session, source_a.id, url="https://a.test/n", title="A", body="Se registraron 6 heridos.", content_hash="ha"
    )
    item_b = _item(
        db_session, source_b.id, url="https://b.test/n", title="B", body="Se registraron 4 heridos.", content_hash="hb"
    )
    event = _event(db_session, item_a)
    _attach(db_session, event, item_b)
    llm = _llm(
        ClaimExtractionBatch(
            claims=[
                _extracted(
                    text="Se registraron 6 heridos",
                    normalized_value="6",
                    object_text="6 heridos",
                    unit="personas",
                    predicate="cantidad_heridos",
                    evidence=[
                        ExtractedEvidence(
                            source_ref=1, evidence_type=EvidenceType.SUPPORTS, excerpt="6 heridos", confidence=0.9
                        )
                    ],
                ),
                _extracted(
                    text="Se registraron 4 heridos",
                    normalized_value="4",
                    object_text="4 heridos",
                    unit="personas",
                    predicate="cantidad_heridos",
                    evidence=[
                        ExtractedEvidence(
                            source_ref=2, evidence_type=EvidenceType.SUPPORTS, excerpt="4 heridos", confidence=0.9
                        )
                    ],
                ),
            ]
        ),
        ClaimResolutionBatch(
            items=[
                ClaimResolutionItem(claim_ref=1, status=ClaimStatus.SUPPORTED, confidence=0.8, reason="a"),
                ClaimResolutionItem(claim_ref=2, status=ClaimStatus.SUPPORTED, confidence=0.8, reason="b"),
            ]
        ),
    )

    _service(db_session, llm).resolve(event.id, trigger="admin")

    statuses = {claim.status for claim in _event_claims(db_session, event.id)}
    assert statuses == {ClaimStatus.CONFLICTING}
    assert db_session.scalar(select(func.count()).select_from(Claim).where(Claim.event_id == event.id)) == 2


def test_invented_excerpt_is_discarded(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(
        db_session,
        source.id,
        url="https://ejemplo.test/choque",
        title="Choque",
        body="Un colectivo chocó en Rosario.",
        content_hash="h1",
    )
    event = _event(db_session, item)
    llm = _llm(
        ClaimExtractionBatch(
            claims=[
                _extracted(
                    text="Hubo doce muertos",
                    evidence=[
                        ExtractedEvidence(
                            source_ref=1,
                            evidence_type=EvidenceType.SUPPORTS,
                            excerpt="hubo doce muertos en el acto",
                            confidence=0.9,
                        )
                    ],
                )
            ]
        )
    )

    result = _service(db_session, llm).resolve(event.id, trigger="admin")

    assert result["persisted"] == 0
    assert db_session.scalar(select(func.count()).select_from(Claim)) == 0
    assert db_session.scalar(select(func.count()).select_from(ClaimEvidence)) == 0
    assert "ClaimResolutionBatch" not in llm.calls


def test_second_run_does_not_duplicate(db_session: Session) -> None:
    source = _source(db_session)
    body = "El choque dejó seis heridos."
    item = _item(
        db_session, source.id, url="https://ejemplo.test/choque", title="Choque", body=body, content_hash="h1"
    )
    event = _event(db_session, item)
    extraction = ClaimExtractionBatch(
        claims=[
            _extracted(
                text="El choque dejó seis heridos",
                normalized_value="6",
                unit="personas",
                predicate="cantidad_heridos",
                evidence=[
                    ExtractedEvidence(
                        source_ref=1, evidence_type=EvidenceType.SUPPORTS, excerpt="seis heridos", confidence=0.9
                    )
                ],
            )
        ]
    )
    resolution = ClaimResolutionBatch(
        items=[
            ClaimResolutionItem(claim_ref=1, status=ClaimStatus.SINGLE_SOURCE, confidence=0.9, reason="ok")
        ]
    )
    service = _service(db_session, _llm(extraction, resolution))
    service.resolve(event.id, trigger="admin")
    service.resolve(event.id, trigger="admin")

    assert db_session.scalar(select(func.count()).select_from(Claim).where(Claim.event_id == event.id)) == 1
    claim = _event_claims(db_session, event.id)[0]
    assert (
        db_session.scalar(select(func.count()).select_from(ClaimEvidence).where(ClaimEvidence.claim_id == claim.id))
        == 1
    )


def test_already_running_lock(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(db_session, source.id, url="https://ejemplo.test/base", title="Base", body="Hecho", content_hash="h1")
    event = _event(db_session, item)
    db_session.add(
        PipelineRun(event_id=event.id, stage=CLAIM_STAGE, status=PipelineStatus.RUNNING, metadata_json={})
    )
    db_session.flush()
    llm = _llm(ClaimExtractionBatch(claims=[]), ClaimResolutionBatch(items=[]))

    result = _service(db_session, llm).resolve(event.id, trigger="admin")

    assert result["skipped"] is True
    assert result["reason"] == "already_running"
    assert llm.calls == []


def test_does_not_change_relation_type_or_event_status(db_session: Session) -> None:
    source = _source(db_session)
    body = "El choque dejó seis heridos."
    item = _item(
        db_session, source.id, url="https://ejemplo.test/choque", title="Choque", body=body, content_hash="h1"
    )
    event = _event(db_session, item, status=EventStatus.PUBLISHED)
    links_before = {
        (link.source_item_id, link.relation_type)
        for link in db_session.scalars(select(EventSource).where(EventSource.event_id == event.id))
    }
    llm = _llm(
        ClaimExtractionBatch(
            claims=[
                _extracted(
                    text="El choque dejó seis heridos",
                    evidence=[
                        ExtractedEvidence(
                            source_ref=1, evidence_type=EvidenceType.SUPPORTS, excerpt="seis heridos", confidence=0.9
                        )
                    ],
                )
            ]
        ),
        ClaimResolutionBatch(
            items=[
                ClaimResolutionItem(claim_ref=1, status=ClaimStatus.SINGLE_SOURCE, confidence=0.9, reason="ok")
            ]
        ),
    )

    _service(db_session, llm).resolve(event.id, trigger="admin")

    db_session.refresh(event)
    assert event.status == EventStatus.PUBLISHED
    links_after = {
        (link.source_item_id, link.relation_type)
        for link in db_session.scalars(select(EventSource).where(EventSource.event_id == event.id))
    }
    assert links_after == links_before


def test_research_event_enqueues_claims_when_not_skipped(monkeypatch) -> None:
    queued: list[tuple] = []

    class Sess:
        def commit(self) -> None:
            pass

        def rollback(self) -> None:
            pass

        def close(self) -> None:
            pass

    monkeypatch.setattr("app.workers.tasks.SessionLocal", Sess)
    monkeypatch.setattr(
        "app.workers.tasks.ResearchService",
        lambda session: SimpleNamespace(research=lambda *_a, **_k: {"skipped": False, "event_id": "eid"}),
    )
    monkeypatch.setattr("app.workers.tasks.resolve_event_claims.delay", lambda *args: queued.append(args))
    from app.workers.tasks import research_event

    research_event.run("00000000-0000-0000-0000-000000000001", "new_event")
    assert queued == [("00000000-0000-0000-0000-000000000001", "new_event")]


def test_research_event_does_not_enqueue_claims_when_skipped(monkeypatch) -> None:
    queued: list[tuple] = []

    class Sess:
        def commit(self) -> None:
            pass

        def rollback(self) -> None:
            pass

        def close(self) -> None:
            pass

    monkeypatch.setattr("app.workers.tasks.SessionLocal", Sess)
    monkeypatch.setattr(
        "app.workers.tasks.ResearchService",
        lambda session: SimpleNamespace(
            research=lambda *_a, **_k: {"skipped": True, "reason": "already_running"}
        ),
    )
    monkeypatch.setattr("app.workers.tasks.resolve_event_claims.delay", lambda *args: queued.append(args))
    from app.workers.tasks import research_event

    research_event.run("00000000-0000-0000-0000-000000000001", "admin")
    assert queued == []


def test_admin_claims_accepted(db_session: Session, monkeypatch) -> None:
    queued: list[tuple] = []
    monkeypatch.setattr("app.api.admin.resolve_event_claims.delay", lambda *args: queued.append(args))
    source = _source(db_session)
    item = _item(db_session, source.id, url="https://ejemplo.test/base", title="Base", body="Hecho", content_hash="h1")
    event = _event(db_session, item)
    db_session.commit()
    settings = get_settings()
    with TestClient(app) as client:
        login = client.post("/api/v1/admin/login", json={"password": settings.admin_password})
        assert login.status_code == 200
        response = client.post(f"/api/v1/admin/events/{event.id}/claims")
    assert response.status_code == 202
    assert response.json()["queued"] is True
    assert queued == [(str(event.id), "admin")]


def test_admin_claims_conflict_when_running(db_session: Session, monkeypatch) -> None:
    queued: list[tuple] = []
    monkeypatch.setattr("app.api.admin.resolve_event_claims.delay", lambda *args: queued.append(args))
    source = _source(db_session)
    item = _item(db_session, source.id, url="https://ejemplo.test/base", title="Base", body="Hecho", content_hash="h1")
    event = _event(db_session, item)
    db_session.add(
        PipelineRun(event_id=event.id, stage=CLAIM_STAGE, status=PipelineStatus.RUNNING, metadata_json={})
    )
    db_session.commit()
    settings = get_settings()
    with TestClient(app) as client:
        client.post("/api/v1/admin/login", json={"password": settings.admin_password})
        response = client.post(f"/api/v1/admin/events/{event.id}/claims")
    assert response.status_code == 409
    assert queued == []
