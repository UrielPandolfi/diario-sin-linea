from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.domain.enums import EntityType, IngestionMethod, PipelineStatus
from app.models import Event, PipelineRun, SourceItem
from app.providers.fakes import FakeEmbeddingProvider, FakeStructuredLLM
from app.providers.registry import ModelRole
from app.schemas import SourceCreate, SourceItemCreate
from app.schemas.detection import EditorialScope, EditorialTopic, EventCandidate, ExtractedEntity, RelevanceLevel
from app.services.detection_service import DetectionService
from app.services.editorial_gate import EditorialFilterReason
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
        "event_type": "anuncio_oficial",
        "what_happened": "El Gobierno dispuso un aumento salarial para las Fuerzas Armadas",
        "occurred_at": datetime(2026, 8, 23, 15, 0, tzinfo=timezone.utc),
        "locality": "Buenos Aires",
        "province": "Buenos Aires",
        "country_code": "AR",
        "short_summary": "Aumento salarial para las Fuerzas Armadas",
        "editorial_topic": EditorialTopic.GOVERNMENT,
        "is_public_affairs": True,
        "political_relevance": RelevanceLevel.HIGH,
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


def test_person_suffix_unifies_inside_the_same_event(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(
        db_session,
        source.id,
        url="https://www.ejemplo.test/bregman",
        title="Bregman habló",
        body="Myriam Bregman habló en el recinto",
        content_hash="brg",
    )
    short = ExtractedEntity(name="Bregman", entity_type=EntityType.PERSON, role="protagonista")
    full = ExtractedEntity(name="Myriam Bregman", entity_type=EntityType.PERSON, role="protagonista")
    llm = FakeStructuredLLM(
        {
            "EventCandidate": _candidate(
                what_happened="Myriam Bregman habló en el recinto",
                short_summary="Bregman habló en el recinto",
                entities=[short, full],
            )
        }
    )
    service = DetectionService(db_session, light_llm=llm, embeddings=FakeEmbeddingProvider())
    result = service.detect(item.id)
    assert result["created"] is True
    names = list(db_session.execute(text("SELECT name FROM entities")).scalars().all())
    assert names == ["Myriam Bregman"]


def test_juan_prefix_is_not_a_person_suffix(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(
        db_session,
        source.id,
        url="https://www.ejemplo.test/juan",
        title="Declaró Pérez",
        body="Juan Pérez habló",
        content_hash="jp",
    )
    first = ExtractedEntity(name="Juan", entity_type=EntityType.PERSON, role="protagonista")
    full = ExtractedEntity(name="Juan Pérez", entity_type=EntityType.PERSON, role="testigo")
    llm = FakeStructuredLLM(
        {
            "EventCandidate": _candidate(
                what_happened="Juan Pérez habló del caso",
                entities=[first, full],
            )
        }
    )
    service = DetectionService(db_session, light_llm=llm, embeddings=FakeEmbeddingProvider())
    service.detect(item.id)
    names = set(db_session.execute(text("SELECT name FROM entities")).scalars().all())
    assert names == {"Juan", "Juan Pérez"}


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


class _CountingEmbed(FakeEmbeddingProvider):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        return super().embed(texts)


def _detect(session: Session, item, candidate: EventCandidate, embeddings=None):
    llm = FakeStructuredLLM({"EventCandidate": candidate})
    embedder = embeddings or FakeEmbeddingProvider()
    service = DetectionService(session, light_llm=llm, embeddings=embedder)
    return service.detect(item.id), embedder, llm


def test_sports_only_is_skipped_without_event(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(
        db_session,
        source.id,
        url="https://www.ejemplo.test/colapinto",
        title="Colapinto 12° en Monza",
        body="Franco Colapinto terminó 12° en el GP de Italia.",
        content_hash="colapinto",
    )
    embeddings = _CountingEmbed()
    result, _, _ = _detect(
        db_session,
        item,
        _candidate(
            event_type="otro",
            what_happened="Colapinto terminó 12° en Monza",
            locality="Monza",
            province=None,
            country_code="IT",
            short_summary="Resultado de F1",
            editorial_scope=EditorialScope.SPORTS_ONLY,
        ),
        embeddings=embeddings,
    )
    refreshed = db_session.get(SourceItem, item.id)
    run = db_session.scalars(
        select(PipelineRun).where(PipelineRun.source_item_id == item.id)
    ).one()
    assert result["created"] is False
    assert result["filtered"] is True
    assert result["reason"] == EditorialFilterReason.SPORTS_ONLY
    assert refreshed is not None
    assert refreshed.processing_status.value == "SKIPPED"
    assert db_session.execute(text("SELECT count(*) FROM events")).scalar_one() == 0
    assert embeddings.calls == 0
    assert run.status == PipelineStatus.SUCCESS
    assert run.metadata_json["filter_reason"] == EditorialFilterReason.SPORTS_ONLY


def test_newells_match_is_skipped(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(
        db_session,
        source.id,
        url="https://www.ejemplo.test/newells",
        title="Newell's ganó",
        body="Newell's le ganó 2-1 a Unión.",
        content_hash="nob",
    )
    result, _, _ = _detect(
        db_session,
        item,
        _candidate(
            editorial_scope=EditorialScope.SPORTS_ONLY,
            what_happened="Newell's ganó 2-1",
            short_summary="Resultado de fútbol",
        ),
    )
    assert result["reason"] == EditorialFilterReason.SPORTS_ONLY
    assert db_session.execute(text("SELECT count(*) FROM events")).scalar_one() == 0


def test_stadium_disturbances_without_public_affairs_are_skipped(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(
        db_session,
        source.id,
        url="https://www.ejemplo.test/disturbios",
        title="Disturbios con heridos",
        body="Hubo disturbios y heridos en el Gigante de Arroyito.",
        content_hash="dist",
    )
    result, _, _ = _detect(
        db_session,
        item,
        _candidate(
            event_type="disturbios",
            what_happened="Disturbios con heridos en un estadio de Rosario",
            locality="Rosario",
            province="Santa Fe",
            short_summary="Incidentes con heridos",
            editorial_scope=EditorialScope.SPORTS_PUBLIC_IMPACT,
            editorial_topic=EditorialTopic.CRIME,
            is_public_affairs=False,
            political_relevance=RelevanceLevel.NONE,
        ),
    )
    assert result["created"] is False
    assert result["reason"] == EditorialFilterReason.SPORTS_ONLY


def test_formative_leagues_are_prefiltered_without_llm(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(
        db_session,
        source.id,
        url="https://www.ejemplo.test/ligas-formativas",
        title="Un fin de semana de tremendos desafíos para los rosarinos en Ligas Formativas: Náutico y Gimnasia son locales",
        body=(
            "Rosario será sede de varios torneos de ligas formativas y Copa Santa Fe "
            "entre Náutico y Gimnasia, con fechas para U15, U17 y femeninas U13."
        ),
        content_hash="ligas",
    )
    llm = FakeStructuredLLM({"EventCandidate": _candidate()})
    result = DetectionService(
        db_session, light_llm=llm, embeddings=FakeEmbeddingProvider()
    ).detect(item.id)
    refreshed = db_session.get(SourceItem, item.id)
    assert result["created"] is False
    assert result["filtered"] is True
    assert result["reason"] == EditorialFilterReason.SPORTS_ONLY
    assert llm.calls == []
    assert refreshed is not None
    assert refreshed.processing_status.value == "SKIPPED"
    assert db_session.execute(text("SELECT count(*) FROM events")).scalar_one() == 0


def test_pellegrini_crash_is_skipped(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(
        db_session,
        source.id,
        url="https://www.ejemplo.test/pellegrini",
        title="Choque en Pellegrini",
        body="Un colectivo chocó en Pellegrini y Corrientes.",
        content_hash="pel",
    )
    result, _, _ = _detect(
        db_session,
        item,
        _candidate(
            event_type="accidente",
            what_happened="Un colectivo chocó en Pellegrini y Corrientes",
            locality="Rosario",
            province="Santa Fe",
            short_summary="Choque de un colectivo en Rosario",
            editorial_topic=EditorialTopic.ACCIDENT,
            is_public_affairs=False,
            political_relevance=RelevanceLevel.NONE,
        ),
    )
    assert result["created"] is False
    assert result["reason"] == EditorialFilterReason.NOT_PUBLIC_AFFAIRS


def test_null_what_happened_uses_summary_as_title(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(
        db_session,
        source.id,
        url="https://www.ejemplo.test/el-cruce",
        title="El Festival El Cruce celebra 25 años",
        body="Se celebra la 25ª edición del Festival El Cruce en Rosario.",
        content_hash="cruce",
    )
    result, _, _ = _detect(
        db_session,
        item,
        _candidate(
            event_type="festival",
            what_happened="null",
            short_summary="Se celebra la 25ª edición del Festival El Cruce en Rosario",
            editorial_topic=EditorialTopic.ENTERTAINMENT,
            is_public_affairs=False,
            political_relevance=RelevanceLevel.NONE,
        ),
    )
    assert result["created"] is False
    assert result["reason"] == EditorialFilterReason.NOT_PUBLIC_AFFAIRS


def test_cordoba_crash_is_skipped(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(
        db_session,
        source.id,
        url="https://www.ejemplo.test/cordoba",
        title="Choque en Córdoba",
        body="Un colectivo chocó en el centro de Córdoba.",
        content_hash="cba",
    )
    result, _, _ = _detect(
        db_session,
        item,
        _candidate(
            locality="Córdoba",
            province="Córdoba",
            editorial_topic=EditorialTopic.ACCIDENT,
            is_public_affairs=False,
            political_relevance=RelevanceLevel.NONE,
            what_happened="Un colectivo chocó en el centro de Córdoba",
            short_summary="Choque en Córdoba",
        ),
    )
    assert result["reason"] == EditorialFilterReason.NOT_PUBLIC_AFFAIRS
    assert db_session.execute(text("SELECT count(*) FROM events")).scalar_one() == 0


def test_cordoba_politics_creates_event(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(
        db_session,
        source.id,
        url="https://www.ejemplo.test/cordoba-presupuesto",
        title="Presupuesto en Córdoba",
        body="La gobernación de Córdoba anunció un recorte presupuestario.",
        content_hash="cbapol",
    )
    result, _, _ = _detect(
        db_session,
        item,
        _candidate(
            locality="Córdoba",
            province="Córdoba",
            editorial_topic=EditorialTopic.PROVINCIAL_POLITICS,
            what_happened="La gobernación de Córdoba anunció un recorte presupuestario",
            short_summary="Recorte presupuestario provincial",
        ),
    )
    assert result["created"] is True


def test_missing_locality_crash_is_skipped(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(
        db_session,
        source.id,
        url="https://www.ejemplo.test/sin-lugar",
        title="Choque",
        body="Un colectivo chocó.",
        content_hash="noloc",
    )
    result, _, _ = _detect(
        db_session,
        item,
        _candidate(
            locality=None,
            province=None,
            editorial_topic=EditorialTopic.ACCIDENT,
            is_public_affairs=False,
            political_relevance=RelevanceLevel.NONE,
            what_happened="Un colectivo chocó",
            short_summary="Choque",
        ),
    )
    assert result["reason"] == EditorialFilterReason.NOT_PUBLIC_AFFAIRS
    assert db_session.get(SourceItem, item.id) is not None


def test_national_politics_without_city_creates_event(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(
        db_session,
        source.id,
        url="https://www.ejemplo.test/dnu",
        title="DNU presidencial",
        body="El Presidente firmó un decreto de necesidad y urgencia.",
        content_hash="dnu1",
    )
    result, _, _ = _detect(
        db_session,
        item,
        _candidate(
            locality=None,
            province=None,
            editorial_topic=EditorialTopic.LEGISLATION,
            what_happened="El Presidente firmó un decreto de necesidad y urgencia",
            short_summary="Decreto presidencial",
        ),
    )
    assert result["created"] is True


def test_ultra_fallback_on_invalid_schema(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(
        db_session,
        source.id,
        url="https://www.ejemplo.test/fallback-schema",
        title="Choque",
        body="Un colectivo chocó en Pellegrini",
        content_hash="fb1",
    )
    ultra = FakeStructuredLLM({"EventCandidate": ValueError("json inválido")})
    light = FakeStructuredLLM({"EventCandidate": _candidate()})
    result = DetectionService(
        db_session, ultra_llm=ultra, light_llm=light, embeddings=FakeEmbeddingProvider()
    ).detect(item.id)
    assert result["created"] is True
    run = db_session.scalars(
        select(PipelineRun).where(PipelineRun.source_item_id == item.id)
    ).one()
    assert run.metadata_json["fallback_reason"] == "invalid_schema"
    assert ultra.calls == ["EventCandidate"]
    assert light.calls == ["EventCandidate"]


def test_ultra_fallback_on_low_location_confidence(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(
        db_session,
        source.id,
        url="https://www.ejemplo.test/fallback-loc",
        title="Choque",
        body="Un colectivo chocó en Pellegrini, Rosario",
        content_hash="fb2",
    )
    ultra = FakeStructuredLLM(
        {
            "EventCandidate": _candidate(
                locality="Rosario", province="Córdoba", location_confidence=0.1
            )
        }
    )
    light = FakeStructuredLLM({"EventCandidate": _candidate()})
    result = DetectionService(
        db_session, ultra_llm=ultra, light_llm=light, embeddings=FakeEmbeddingProvider()
    ).detect(item.id)
    assert result["created"] is True
    run = db_session.scalars(
        select(PipelineRun).where(PipelineRun.source_item_id == item.id)
    ).one()
    assert run.metadata_json["fallback_reason"] == "low_location_confidence"


def test_missing_ultra_config_uses_light_processing(db_session: Session, monkeypatch) -> None:
    source = _source(db_session)
    item = _item(
        db_session,
        source.id,
        url="https://www.ejemplo.test/sin-ultra",
        title="Choque",
        body="Un colectivo chocó en Pellegrini",
        content_hash="nu1",
    )
    light = FakeStructuredLLM({"EventCandidate": _candidate()})

    def provider(role: ModelRole):
        if role == ModelRole.LIGHT_PROCESSING:
            return light
        raise AssertionError(f"rol inesperado {role}")

    monkeypatch.setattr(
        "app.services.detection_service.get_structured_provider_optional",
        lambda role: None,
    )
    monkeypatch.setattr("app.services.detection_service.get_structured_provider", provider)
    result = DetectionService(db_session, embeddings=FakeEmbeddingProvider()).detect(item.id)
    assert result["created"] is True
    assert light.calls == ["EventCandidate"]


def test_person_name_suffix_is_lastname_not_prefix() -> None:
    from app.core.text import is_person_name_suffix

    assert is_person_name_suffix("Bregman", "Myriam Bregman")
    assert is_person_name_suffix("Myriam Bregman", "Bregman")
    assert is_person_name_suffix("Bregman", "Myriam Bregman") is True
    assert not is_person_name_suffix("Juan", "Juan Pérez")
    assert not is_person_name_suffix("Juan Pérez", "Ana Pérez")
