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


def test_extracted_claim_coerces_numeric_normalized_value() -> None:
    batch = ClaimExtractionBatch.model_validate(
        {
            "claims": [
                {
                    "canonical_text": "Valuaron los pingüinos en 6 millones",
                    "normalized_value": 6000000,
                    "evidence": [],
                },
                {
                    "canonical_text": "Elecciones en 2027",
                    "normalized_value": 2027,
                    "evidence": [],
                },
                {
                    "canonical_text": "Sin cifra",
                    "normalized_value": None,
                    "evidence": [],
                },
            ]
        }
    )
    assert batch.claims[0].normalized_value == "6000000"
    assert batch.claims[1].normalized_value == "2027"
    assert batch.claims[2].normalized_value is None
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


def _item(
    session: Session,
    source_id,
    *,
    url: str,
    title: str,
    body: str,
    content_hash: str,
    published_at: datetime | None = None,
):
    return SourceItemService(session).ingest(
        SourceItemCreate(
            source_id=source_id,
            url=url,
            canonical_url=url,
            content_hash=content_hash,
            title=title,
            clean_text=body,
            published_at=published_at,
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
    occurred_at: datetime | None = None,
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
        occurred_at=occurred_at,
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


def test_conflicting_same_moment_competing_values(db_session: Session) -> None:
    when = datetime(2026, 8, 24, 16, 0, tzinfo=timezone.utc)
    source_a = _source(db_session, name="A", domain="a.test", feed_url="https://a.test/rss.xml")
    source_b = _source(db_session, name="B", domain="b.test", feed_url="https://b.test/rss.xml")
    item_a = _item(
        db_session,
        source_a.id,
        url="https://a.test/n",
        title="A",
        body="Se registraron 4 heridos.",
        content_hash="ha",
        published_at=when,
    )
    item_b = _item(
        db_session,
        source_b.id,
        url="https://b.test/n",
        title="B",
        body="Se registraron 6 heridos.",
        content_hash="hb",
        published_at=when,
    )
    event = _event(db_session, item_a)
    _attach(db_session, event, item_b)
    llm = _llm(
        ClaimExtractionBatch(
            claims=[
                _extracted(
                    text="Se registraron 4 heridos",
                    normalized_value="4",
                    object_text="4 heridos",
                    unit="personas",
                    predicate="cantidad_heridos",
                    occurred_at=when,
                    evidence=[
                        ExtractedEvidence(
                            source_ref=1, evidence_type=EvidenceType.SUPPORTS, excerpt="4 heridos", confidence=0.9
                        )
                    ],
                ),
                _extracted(
                    text="Se registraron 6 heridos",
                    normalized_value="6",
                    object_text="6 heridos",
                    unit="personas",
                    predicate="cantidad_heridos",
                    occurred_at=when,
                    evidence=[
                        ExtractedEvidence(
                            source_ref=2, evidence_type=EvidenceType.SUPPORTS, excerpt="6 heridos", confidence=0.9
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

    claims = _event_claims(db_session, event.id)
    assert {claim.status for claim in claims} == {ClaimStatus.CONFLICTING}
    assert db_session.scalar(select(func.count()).select_from(Claim).where(Claim.event_id == event.id)) == 2


def test_later_count_is_update_not_automatic_conflict(db_session: Session) -> None:
    at_15 = datetime(2026, 8, 24, 15, 0, tzinfo=timezone.utc)
    at_17 = datetime(2026, 8, 24, 17, 0, tzinfo=timezone.utc)
    source_a = _source(db_session, name="A", domain="a.test", feed_url="https://a.test/rss.xml")
    source_b = _source(db_session, name="B", domain="b.test", feed_url="https://b.test/rss.xml")
    item_a = _item(
        db_session,
        source_a.id,
        url="https://a.test/15",
        title="A",
        body="A las 15:00 se registraron 4 heridos.",
        content_hash="ha",
        published_at=at_15,
    )
    item_b = _item(
        db_session,
        source_b.id,
        url="https://b.test/17",
        title="B",
        body="A las 17:00 se confirmaron 6 heridos.",
        content_hash="hb",
        published_at=at_17,
    )
    event = _event(db_session, item_a)
    _attach(db_session, event, item_b)
    llm = _llm(
        ClaimExtractionBatch(
            claims=[
                _extracted(
                    text="Se registraron 4 heridos",
                    normalized_value="4",
                    object_text="4 heridos",
                    unit="personas",
                    predicate="cantidad_heridos",
                    occurred_at=at_15,
                    evidence=[
                        ExtractedEvidence(
                            source_ref=1, evidence_type=EvidenceType.SUPPORTS, excerpt="4 heridos", confidence=0.9
                        )
                    ],
                ),
                _extracted(
                    text="Se confirmaron 6 heridos",
                    normalized_value="6",
                    object_text="6 heridos",
                    unit="personas",
                    predicate="cantidad_heridos",
                    occurred_at=at_17,
                    evidence=[
                        ExtractedEvidence(
                            source_ref=2, evidence_type=EvidenceType.SUPPORTS, excerpt="6 heridos", confidence=0.9
                        )
                    ],
                ),
            ]
        ),
        ClaimResolutionBatch(
            items=[
                ClaimResolutionItem(claim_ref=1, status=ClaimStatus.CONFLICTING, confidence=0.8, reason="grupo"),
                ClaimResolutionItem(claim_ref=2, status=ClaimStatus.CONFLICTING, confidence=0.8, reason="grupo"),
            ]
        ),
    )

    _service(db_session, llm).resolve(event.id, trigger="admin")

    by_value = {claim.normalized_value: claim.status for claim in _event_claims(db_session, event.id)}
    assert by_value["4"] == ClaimStatus.OUTDATED
    assert by_value["6"] == ClaimStatus.SINGLE_SOURCE
    assert ClaimStatus.CONFLICTING not in by_value.values()
    resolution_prompt = llm.user_prompts[llm.calls.index("ClaimResolutionBatch")]
    assert "occurred_at=" in resolution_prompt
    assert "published_at=" in resolution_prompt
    assert "15:00" in resolution_prompt or "15:00:00" in resolution_prompt
    assert "17:00" in resolution_prompt or "17:00:00" in resolution_prompt


def test_competing_values_without_time_are_uncertain(db_session: Session) -> None:
    source_a = _source(db_session, name="A", domain="a.test", feed_url="https://a.test/rss.xml")
    source_b = _source(db_session, name="B", domain="b.test", feed_url="https://b.test/rss.xml")
    item_a = _item(
        db_session, source_a.id, url="https://a.test/n", title="A", body="Se registraron 4 heridos.", content_hash="ha"
    )
    item_b = _item(
        db_session, source_b.id, url="https://b.test/n", title="B", body="Se registraron 6 heridos.", content_hash="hb"
    )
    event = _event(db_session, item_a)
    _attach(db_session, event, item_b)
    llm = _llm(
        ClaimExtractionBatch(
            claims=[
                _extracted(
                    text="Se registraron 4 heridos",
                    normalized_value="4",
                    object_text="4 heridos",
                    unit="personas",
                    predicate="cantidad_heridos",
                    evidence=[
                        ExtractedEvidence(
                            source_ref=1, evidence_type=EvidenceType.SUPPORTS, excerpt="4 heridos", confidence=0.9
                        )
                    ],
                ),
                _extracted(
                    text="Se registraron 6 heridos",
                    normalized_value="6",
                    object_text="6 heridos",
                    unit="personas",
                    predicate="cantidad_heridos",
                    evidence=[
                        ExtractedEvidence(
                            source_ref=2, evidence_type=EvidenceType.SUPPORTS, excerpt="6 heridos", confidence=0.9
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

    assert {claim.status for claim in _event_claims(db_session, event.id)} == {ClaimStatus.UNCERTAIN}


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
        ),
        ClaimResolutionBatch(items=[]),
    )

    result = _service(db_session, llm).resolve(event.id, trigger="admin")

    claims = _event_claims(db_session, event.id)
    assert result["persisted"] >= 1
    assert result["fallback_used"] is True
    assert all("doce" not in claim.canonical_text.lower() for claim in claims)
    assert any("colectivo" in claim.canonical_text.lower() for claim in claims)
    assert db_session.scalar(select(func.count()).select_from(ClaimEvidence)) >= 1
    assert "ClaimResolutionBatch" in llm.calls


def test_empty_extraction_falls_back_to_source_sentences(db_session: Session) -> None:
    source = _source(db_session)
    body = "Un colectivo chocó contra un automóvil en avenida Pellegrini y hubo cuatro heridos."
    item = _item(
        db_session,
        source.id,
        url="https://ejemplo.test/choque",
        title="Choque en Pellegrini",
        body=body,
        content_hash="fb",
    )
    event = _event(db_session, item)
    llm = _llm(
        ClaimExtractionBatch(claims=[]),
        ClaimResolutionBatch(items=[]),
    )

    result = _service(db_session, llm).resolve(event.id, trigger="admin")

    claims = _event_claims(db_session, event.id)
    assert result["extracted"] == 0
    assert result["fallback_used"] is True
    assert result["persisted"] >= 1
    assert any("colectivo" in claim.canonical_text.lower() for claim in claims)


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


def test_low_confidence_resolution_is_escalated(db_session: Session) -> None:
    source = _source(db_session)
    body = "El choque dejó seis heridos en Rosario."
    item = _item(
        db_session, source.id, url="https://ejemplo.test/choque", title="Choque", body=body, content_hash="esc1"
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
                        source_ref=1,
                        evidence_type=EvidenceType.SUPPORTS,
                        excerpt="seis heridos",
                        confidence=0.9,
                    )
                ],
            )
        ]
    )
    extractor = FakeStructuredLLM({"ClaimExtractionBatch": extraction})
    flash = FakeStructuredLLM(
        {
            "ClaimResolutionBatch": ClaimResolutionBatch(
                items=[
                    ClaimResolutionItem(
                        claim_ref=1,
                        status=ClaimStatus.UNCERTAIN,
                        confidence=0.2,
                        conflicts=["cifras distintas"],
                        needs_external_verification=True,
                    )
                ]
            )
        }
    )
    escalated = FakeStructuredLLM(
        {
            "ClaimResolutionBatch": ClaimResolutionBatch(
                items=[
                    ClaimResolutionItem(
                        claim_ref=1,
                        status=ClaimStatus.SUPPORTED,
                        confidence=0.9,
                        reason="escalado",
                    )
                ]
            )
        }
    )
    result = ClaimService(
        db_session,
        extractor_llm=extractor,
        resolver_llm=flash,
        escalated_resolver_llm=escalated,
    ).resolve(event.id, trigger="admin")
    assert result["escalated_claim_refs"] == [1]
    assert flash.calls.count("ClaimResolutionBatch") == 1
    assert escalated.calls.count("ClaimResolutionBatch") == 1


def test_high_confidence_resolution_is_not_escalated(db_session: Session) -> None:
    source = _source(db_session)
    body = "El choque dejó seis heridos en Rosario."
    item = _item(
        db_session, source.id, url="https://ejemplo.test/choque2", title="Choque", body=body, content_hash="esc2"
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
                    claim_ref=1, status=ClaimStatus.SUPPORTED, confidence=0.9, reason="claro"
                )
            ]
        ),
    )
    escalated = FakeStructuredLLM({"ClaimResolutionBatch": ClaimResolutionBatch(items=[])})
    result = ClaimService(
        db_session,
        extractor_llm=llm,
        resolver_llm=llm,
        escalated_resolver_llm=escalated,
    ).resolve(event.id, trigger="admin")
    assert result["escalated_claim_refs"] == []
    assert escalated.calls == []


def test_extraction_prompt_includes_material_after_1500_chars(db_session: Session, monkeypatch) -> None:
    lead = ("Medida administrativa del Ejecutivo. " * 50).strip()
    assert len(lead) > 1500
    late = "El aumento para las Fuerzas Armadas será del 12,22%."
    body = f"{lead}\n\n{late}"
    source = _source(db_session)
    item = _item(
        db_session,
        source.id,
        url="https://ejemplo.test/ffaa",
        title="Aumento FFAA",
        body=body,
        content_hash="ffaa5000",
    )
    event = _event(
        db_session,
        item,
        title_internal="Aumento para las Fuerzas Armadas",
        event_type="anuncio_oficial",
    )
    service = ClaimService(db_session, extractor_llm=FakeStructuredLLM({}), resolver_llm=FakeStructuredLLM({}))

    monkeypatch.setattr(service.settings, "claim_extraction_source_chars", 1500)
    short_prompt = service._extraction_prompt(event, [item])
    assert "12,22%" not in short_prompt

    monkeypatch.setattr(service.settings, "claim_extraction_source_chars", 5000)
    long_prompt = service._extraction_prompt(event, [item])
    assert "12,22%" in long_prompt
