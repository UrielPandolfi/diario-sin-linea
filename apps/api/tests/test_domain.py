from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.domain.enums import EventSourceRelation, IngestionMethod, SourceItemStatus
from app.schemas import ArticleContentUpdate, ArticleCreate, EventCreate, SourceCreate, SourceItemCreate
from app.services import ArticleService, EventService, SourceItemService, SourceService


def _source(session: Session, **overrides) -> object:
    payload = {
        "name": "Rosario3",
        "domain": "rosario3.com",
        "preferred_ingestion_method": IngestionMethod.RSS,
        "feed_url": "https://www.rosario3.com/rss.xml",
        "is_monitored": True,
        "is_enabled": True,
    }
    payload.update(overrides)
    return SourceService(session).create(SourceCreate(**payload))


def test_pgvector_extension_enabled(db_session: Session) -> None:
    name = db_session.execute(text("SELECT extname FROM pg_extension WHERE extname = 'vector'")).scalar_one()
    assert name == "vector"


def test_pollable_sources_require_monitored_and_enabled(db_session: Session) -> None:
    service = SourceService(db_session)
    monitored = _source(db_session, name="Monitoreada")
    _source(db_session, name="Registrada", is_monitored=False, is_enabled=True)
    _source(db_session, name="Apagada", is_monitored=True, is_enabled=False)

    pollable = service.list_pollable()
    assert [source.id for source in pollable] == [monitored.id]


def test_source_item_ingest_is_idempotent_by_identity(db_session: Session) -> None:
    source = _source(db_session)
    service = SourceItemService(db_session)
    payload = SourceItemCreate(
        source_id=source.id,
        url="https://www.rosario3.com/choque",
        canonical_url="https://www.rosario3.com/choque",
        external_id="guid-1",
        content_hash="abc123",
        title="Choque en Pellegrini",
    )

    first = service.ingest(payload)
    second = service.ingest(payload)

    assert first.created is True
    assert second.created is False
    assert second.updated is False
    assert first.item.id == second.item.id
    count = db_session.execute(text("SELECT count(*) FROM source_items")).scalar_one()
    assert count == 1


def test_source_item_content_change_updates_same_row(db_session: Session) -> None:
    source = _source(db_session)
    service = SourceItemService(db_session)
    first = service.ingest(
        SourceItemCreate(
            source_id=source.id,
            url="https://www.rosario3.com/choque",
            canonical_url="https://www.rosario3.com/choque",
            external_id="guid-1",
            content_hash="hash-inicial",
            title="Choque en Pellegrini",
            clean_text="Versión breve",
        )
    )
    second = service.ingest(
        SourceItemCreate(
            source_id=source.id,
            url="https://www.rosario3.com/choque",
            canonical_url="https://www.rosario3.com/choque",
            external_id="guid-1",
            content_hash="hash-actualizado",
            title="Choque en Pellegrini: hay heridos",
            clean_text="Versión ampliada con heridos",
        )
    )

    assert first.created is True
    assert second.created is False
    assert second.updated is True
    assert first.item.id == second.item.id
    assert second.item.content_hash == "hash-actualizado"
    assert second.item.clean_text == "Versión ampliada con heridos"
    count = db_session.execute(text("SELECT count(*) FROM source_items")).scalar_one()
    assert count == 1


def test_event_source_link_is_unique(db_session: Session) -> None:
    source = _source(db_session)
    item = SourceItemService(db_session).ingest(
        SourceItemCreate(
            source_id=source.id,
            url="https://www.rosario3.com/choque",
            content_hash="evt-1",
            title="Choque",
        )
    ).item
    event_service = EventService(db_session)
    event = event_service.create(
        EventCreate(
            title_internal="Choque de colectivos en Pellegrini y Corrientes",
            locality="Rosario",
            province="Santa Fe",
            source_item_id=item.id,
        )
    )

    link, created = event_service.attach_source(
        event,
        item.id,
        relation_type=EventSourceRelation.INITIAL,
        is_primary=True,
    )

    assert created is False
    assert link.event_id == event.id
    assert len(event.event_sources) == 1


def test_article_update_preserves_previous_version(db_session: Session) -> None:
    source = _source(db_session)
    item = SourceItemService(db_session).ingest(
        SourceItemCreate(
            source_id=source.id,
            url="https://www.rosario3.com/choque",
            content_hash="art-1",
        )
    ).item
    event = EventService(db_session).create(
        EventCreate(title_internal="Choque de colectivos", source_item_id=item.id)
    )
    article_service = ArticleService(db_session)
    article, created = article_service.create_draft(
        ArticleCreate(
            event_id=event.id,
            headline="Un colectivo chocó en avenida Pellegrini",
            summary="Dos unidades colisionaron esta tarde.",
            body="El choque ocurrió en Pellegrini y Corrientes.",
        )
    )
    assert created is True
    original_headline = article.headline

    article_service.update_content(
        article,
        ArticleContentUpdate(
            headline="Un colectivo chocó en Pellegrini y hubo heridos",
            summary="El choque dejó heridos, según fuentes locales.",
            body="Fuentes locales informaron que el choque dejó heridos.",
            change_reason="nueva información material",
        ),
    )

    db_session.refresh(article)
    assert article.current_version == 2
    assert len(article.versions) == 2
    first_version = next(version for version in article.versions if version.version_number == 1)
    assert first_version.headline == original_headline
    assert article.headline != original_headline

    again, created_again = article_service.create_draft(
        ArticleCreate(
            event_id=event.id,
            headline="otro",
            summary="otro",
            body="otro",
        )
    )
    assert created_again is False
    assert again.id == article.id


def test_enrich_content_fills_body_without_clobbering_metadata(db_session: Session) -> None:
    source = _source(db_session)
    published = datetime(2026, 8, 20, tzinfo=timezone.utc)
    item = SourceItemService(db_session).ingest(
        SourceItemCreate(
            source_id=source.id,
            url="https://www.rosario3.com/choque",
            canonical_url="https://www.rosario3.com/choque",
            content_hash="h1",
            title="Choque en Pellegrini",
            author="Redacción",
            published_at=published,
            clean_text=None,
        )
    ).item
    item.processing_status = SourceItemStatus.PROCESSED
    db_session.flush()

    updated = SourceItemService(db_session).enrich_content(
        item,
        title=None,
        author="",
        published_at=None,
        clean_text="La Policía confirmó un choque en Pellegrini y Corrientes.",
        raw_text="<article><p>html</p></article>",
    )

    assert updated is True
    assert item.title == "Choque en Pellegrini"
    assert item.author == "Redacción"
    assert item.published_at == published
    assert item.processing_status == SourceItemStatus.PROCESSED
    assert item.clean_text == "La Policía confirmó un choque en Pellegrini y Corrientes."


def test_enrich_content_does_not_replace_body_with_title(db_session: Session) -> None:
    source = _source(db_session)
    summary = "La Policía confirmó un homicidio en barrio Alvear."
    item = SourceItemService(db_session).ingest(
        SourceItemCreate(
            source_id=source.id,
            url="https://www.rosario3.com/homicidio",
            canonical_url="https://www.rosario3.com/homicidio",
            content_hash="h-sum",
            title="Homicidio en Ayacucho 4100",
            clean_text=summary,
        )
    ).item

    updated = SourceItemService(db_session).enrich_content(
        item,
        title="Homicidio en Ayacucho 4100",
        clean_text="Homicidio en Ayacucho 4100",
        excerpt="Homicidio en Ayacucho 4100",
    )

    assert updated is False
    assert item.clean_text == summary


def test_ingest_strips_nul_bytes_from_text_fields(db_session: Session) -> None:
    source = _source(db_session)
    item = SourceItemService(db_session).ingest(
        SourceItemCreate(
            source_id=source.id,
            url="https://www.indec.gob.ar/uploads/ipc.pdf",
            canonical_url="https://www.indec.gob.ar/uploads/ipc.pdf",
            content_hash="h-nul",
            title="IPC",
            raw_text="%PDF-1.7\x00trailer",
            clean_text="El IPC subió 2,1%\x00",
            excerpt="El IPC subió 2,1%\x00",
        )
    ).item
    db_session.flush()
    assert "\x00" not in (item.raw_text or "")
    assert item.clean_text == "El IPC subió 2,1%"
    assert item.excerpt == "El IPC subió 2,1%"
