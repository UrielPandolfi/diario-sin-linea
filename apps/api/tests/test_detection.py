from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.domain.enums import EntityType, IngestionMethod
from app.providers.fakes import FakeEmbeddingProvider, FakeStructuredLLM
from app.schemas import SourceCreate, SourceItemCreate
from app.schemas.detection import EventCandidate, ExtractedEntity
from app.services.detection_service import DetectionService
from app.services.source_item_service import SourceItemService
from app.services.source_service import SourceService


def _source(session: Session, name: str = "Fuente"):
    return SourceService(session).create(
        SourceCreate(
            name=name,
            preferred_ingestion_method=IngestionMethod.RSS,
            feed_url="https://www.ejemplo.test/rss.xml",
            is_monitored=True,
            is_enabled=True,
        )
    )


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


def _candidate(**overrides) -> EventCandidate:
    payload = {
        "event_type": "accidente",
        "what_happened": "Un colectivo chocó en Pellegrini y Corrientes",
        "occurred_at": datetime(2026, 8, 23, 15, 0, tzinfo=timezone.utc),
        "locality": "Rosario",
        "province": "Santa Fe",
        "short_summary": "Choque de un colectivo en Rosario",
        "entities": [],
    }
    payload.update(overrides)
    return EventCandidate(**payload)


def test_new_item_creates_event(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(
        db_session,
        source.id,
        url="https://www.ejemplo.test/choque-1",
        title="Choque",
        body="Un colectivo chocó en Pellegrini",
        content_hash="h1",
    )
    llm = FakeStructuredLLM({"EventCandidate": _candidate()})
    service = DetectionService(db_session, light_llm=llm, embeddings=FakeEmbeddingProvider())

    result = service.detect(item.id)

    assert result["created"] is True
    count = db_session.execute(text("SELECT count(*) FROM events")).scalar_one()
    assert count == 1
    assert "EventCandidate" in llm.calls
    assert "DedupDecision" not in llm.calls


def test_same_url_relink_skips_duplicate_entity_roles(db_session: Session) -> None:
    """Segunda fuente del mismo hecho no debe explotar por uq_event_entities."""
    source_a = _source(db_session, name="A")
    source_b = _source(db_session, name="B")
    person = ExtractedEntity(name="Donald Trump", entity_type=EntityType.PERSON, role="protagonista")
    org = ExtractedEntity(
        name="Departamento de Estado",
        entity_type=EntityType.GOVERNMENT,
        role="organismo",
    )
    item_a = _item(
        db_session,
        source_a.id,
        url="https://www.ejemplo.test/visas",
        title="EEUU suspende visas",
        body="Suspenden citas de visas",
        content_hash="va",
    )
    item_b = _item(
        db_session,
        source_b.id,
        url="https://www.ejemplo.test/visas",
        title="EEUU frena citas",
        body="Capacitación consular",
        content_hash="vb",
    )
    llm = FakeStructuredLLM(
        {
            "EventCandidate": [
                _candidate(
                    event_type="anuncio_oficial",
                    what_happened="EEUU suspende citas de visas",
                    short_summary="Pausa consular",
                    entities=[person, org],
                ),
                _candidate(
                    event_type="anuncio_oficial",
                    what_happened="EEUU frena citas de visas inmigrante",
                    short_summary="Misma pausa consular",
                    entities=[person, org, person],
                ),
            ]
        }
    )
    service = DetectionService(db_session, light_llm=llm, embeddings=FakeEmbeddingProvider())

    first = service.detect(item_a.id)
    second = service.detect(item_b.id)

    assert first["created"] is True
    assert second["created"] is False
    assert first["event_id"] == second["event_id"]
    link_count = db_session.execute(text("SELECT count(*) FROM event_entities")).scalar_one()
    assert link_count == 2
    from app.models import SourceItem

    refreshed = db_session.get(SourceItem, item_b.id)
    assert refreshed is not None
    assert refreshed.processing_status.value == "PROCESSED"


def test_same_url_links_without_creating_another_event(db_session: Session) -> None:
    source_a = _source(db_session, name="A")
    source_b = _source(db_session, name="B")
    item_a = _item(
        db_session,
        source_a.id,
        url="https://www.ejemplo.test/misma-nota",
        title="Choque",
        body="Un colectivo chocó en Pellegrini",
        content_hash="ha",
    )
    item_b = _item(
        db_session,
        source_b.id,
        url="https://www.ejemplo.test/misma-nota",
        title="Choque",
        body="Un colectivo chocó en Pellegrini",
        content_hash="hb",
    )
    llm = FakeStructuredLLM({"EventCandidate": _candidate()})
    service = DetectionService(db_session, light_llm=llm, embeddings=FakeEmbeddingProvider())

    first = service.detect(item_a.id)
    second = service.detect(item_b.id)

    assert first["created"] is True
    assert second["created"] is False
    assert first["event_id"] == second["event_id"]
    count = db_session.execute(text("SELECT count(*) FROM events")).scalar_one()
    assert count == 1


def test_same_day_type_locality_without_strong_overlap_does_not_merge(db_session: Session) -> None:
    source = _source(db_session)
    item_a = _item(
        db_session,
        source.id,
        url="https://www.ejemplo.test/incendio-norte",
        title="Incendio en zona norte",
        body="Ardió un depósito en zona norte",
        content_hash="inc-1",
    )
    item_b = _item(
        db_session,
        source.id,
        url="https://www.ejemplo.test/incendio-sur",
        title="Incendio en zona sur",
        body="Ardió un taller en zona sur",
        content_hash="inc-2",
    )
    llm = FakeStructuredLLM(
        {
            "EventCandidate": [
                _candidate(
                    event_type="incendio",
                    what_happened="Ardió un depósito en zona norte de Rosario",
                    short_summary="Incendio de depósito en el norte",
                    entities=[],
                ),
                _candidate(
                    event_type="incendio",
                    what_happened="Ardió un taller mecánico en zona sur de Rosario",
                    short_summary="Incendio de taller en el sur",
                    entities=[],
                ),
            ]
        }
    )
    service = DetectionService(db_session, light_llm=llm, embeddings=FakeEmbeddingProvider())

    first = service.detect(item_a.id)
    second = service.detect(item_b.id)

    assert first["created"] is True
    assert second["created"] is True
    assert first["event_id"] != second["event_id"]
    count = db_session.execute(text("SELECT count(*) FROM events")).scalar_one()
    assert count == 2
    assert "DedupDecision" not in llm.calls


def test_entities_are_not_merged_across_events(db_session: Session) -> None:
    source = _source(db_session)
    item_a = _item(
        db_session,
        source.id,
        url="https://www.ejemplo.test/nota-a",
        title="Declaró Pérez",
        body="Juan Pérez habló del primer caso",
        content_hash="ea",
    )
    item_b = _item(
        db_session,
        source.id,
        url="https://www.ejemplo.test/nota-b",
        title="Otro caso",
        body="Juan Pérez apareció en un hecho distinto",
        content_hash="eb",
    )
    person = ExtractedEntity(name="Juan Pérez", entity_type=EntityType.PERSON, role="protagonista")
    llm = FakeStructuredLLM(
        {
            "EventCandidate": [
                _candidate(what_happened="Primer hecho distinto en el norte", entities=[person]),
                _candidate(what_happened="Segundo hecho distinto en el sur", entities=[person]),
            ]
        }
    )
    service = DetectionService(db_session, light_llm=llm, embeddings=FakeEmbeddingProvider())

    first = service.detect(item_a.id)
    second = service.detect(item_b.id)

    assert first["event_id"] != second["event_id"]
    entity_count = db_session.execute(text("SELECT count(*) FROM entities")).scalar_one()
    assert entity_count == 2


def test_content_update_of_same_item_does_not_create_another_event(db_session: Session) -> None:
    source = _source(db_session)
    items = SourceItemService(db_session)
    first = items.ingest(
        SourceItemCreate(
            source_id=source.id,
            url="https://www.ejemplo.test/choque-actualizado",
            canonical_url="https://www.ejemplo.test/choque-actualizado",
            external_id="guid-update-1",
            content_hash="hash-1",
            title="Choque",
            clean_text="Versión breve",
        )
    )
    llm = FakeStructuredLLM({"EventCandidate": _candidate()})
    service = DetectionService(db_session, light_llm=llm, embeddings=FakeEmbeddingProvider())

    created = service.detect(first.item.id)
    updated = items.ingest(
        SourceItemCreate(
            source_id=source.id,
            url="https://www.ejemplo.test/choque-actualizado",
            canonical_url="https://www.ejemplo.test/choque-actualizado",
            external_id="guid-update-1",
            content_hash="hash-2",
            title="Choque: hay heridos",
            clean_text="Versión ampliada",
        )
    )
    again = service.detect(updated.item.id)

    assert first.item.id == updated.item.id
    assert created["created"] is True
    assert again["created"] is False
    assert created["event_id"] == again["event_id"]
    count = db_session.execute(text("SELECT count(*) FROM events")).scalar_one()
    assert count == 1
