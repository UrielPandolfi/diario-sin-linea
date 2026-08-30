from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.domain.enums import EventSourceRelation, EventStatus, IngestionMethod, PipelineStatus
from app.main import app
from app.models import EventSource, PipelineRun
from app.providers.base import ProviderNotConfiguredError, SearchHit
from app.providers.fakes import FakeSearchProvider, FakeStructuredLLM, RecordingFetcher
from app.schemas import EventCreate, SourceCreate, SourceItemCreate
from app.schemas.research import RelevanceHit, RelevanceBatch, ResearchQueries, ResearchRelevance
from app.services.event_service import EventService
from app.services.research_service import ResearchService
from app.services.source_item_service import SourceItemService
from app.services.source_service import SourceService


def _source(session: Session, **overrides):
    payload = {
        "name": "Fuente",
        "preferred_ingestion_method": IngestionMethod.RSS,
        "feed_url": "https://www.ejemplo.test/rss.xml",
        "is_monitored": True,
        "is_enabled": True,
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


def _llm(queries: list[str], relevant_urls: list[str]) -> FakeStructuredLLM:
    return FakeStructuredLLM(
        {
            "ResearchQueries": ResearchQueries(queries=queries),
            "RelevanceBatch": RelevanceBatch(
                hits=[
                    RelevanceHit(url=url, classification=ResearchRelevance.SAME_EVENT)
                    for url in relevant_urls
                ]
            ),
        }
    )


def _links(session: Session, event_id) -> list[EventSource]:
    return list(session.scalars(select(EventSource).where(EventSource.event_id == event_id)))


def test_research_attaches_additional_sources(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(
        db_session,
        source.id,
        url="https://www.ejemplo.test/choque",
        title="Choque",
        body="Un colectivo chocó",
        content_hash="h1",
    )
    event = _event(db_session, item)
    url = "https://otro.test/cobertura"
    llm = _llm(["choque rosario colectivo"], [url])
    search = FakeSearchProvider([SearchHit(title="Cobertura", url=url, snippet="Otro medio")])
    fetcher = RecordingFetcher()
    service = ResearchService(db_session, llm=llm, search=search, fetcher=fetcher)

    result = service.research(event.id, trigger="new_event")

    assert result["skipped"] is False
    assert result["attached"] == 1
    assert result["fetched"] == 1
    assert fetcher.fetched == [url]
    assert all(query.freshness for query in search.queries)
    links = _links(db_session, event.id)
    additional = [link for link in links if link.relation_type == EventSourceRelation.ADDITIONAL]
    assert len(additional) == 1
    assert additional[0].is_primary is False
    run = db_session.scalars(
        select(PipelineRun).where(PipelineRun.event_id == event.id, PipelineRun.stage == "research")
    ).one()
    assert run.status == PipelineStatus.SUCCESS


def test_already_linked_url_is_skipped(db_session: Session) -> None:
    source = _source(db_session)
    url = "https://www.ejemplo.test/choque"
    item = _item(db_session, source.id, url=url, title="Choque", body="Un colectivo chocó", content_hash="h1")
    event = _event(db_session, item)
    llm = _llm(["choque"], [url])
    search = FakeSearchProvider([SearchHit(title="Misma nota", url=url, snippet="dup")])
    fetcher = RecordingFetcher()
    service = ResearchService(db_session, llm=llm, search=search, fetcher=fetcher)

    result = service.research(event.id, trigger="admin")

    assert result["attached"] == 0
    assert fetcher.fetched == []
    assert db_session.scalar(select(func.count()).select_from(EventSource).where(EventSource.event_id == event.id)) == 1


def test_global_source_item_is_reused_without_fetch(db_session: Session) -> None:
    source_a = _source(db_session, name="A")
    source_b = _source(db_session, name="B", feed_url="https://b.test/rss.xml")
    item_a = _item(
        db_session,
        source_a.id,
        url="https://a.test/choque",
        title="Choque",
        body="Un colectivo chocó",
        content_hash="ha",
    )
    orphan = _item(
        db_session,
        source_b.id,
        url="https://b.test/ya-existia",
        title="Otra cobertura",
        body="La misma colisión",
        content_hash="hb",
    )
    event = _event(db_session, item_a)
    llm = _llm(["choque"], [orphan.url])
    search = FakeSearchProvider([SearchHit(title="Otra cobertura", url=orphan.url, snippet="colisión")])
    fetcher = RecordingFetcher()
    service = ResearchService(db_session, llm=llm, search=search, fetcher=fetcher)

    result = service.research(event.id, trigger="admin")

    assert result["reused"] == 1
    assert result["fetched"] == 0
    assert fetcher.fetched == []
    links = _links(db_session, event.id)
    assert any(
        link.source_item_id == orphan.id and link.relation_type == EventSourceRelation.ADDITIONAL
        for link in links
    )


def test_relevance_happens_before_fetch(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(
        db_session, source.id, url="https://ejemplo.test/base", title="Base", body="Hecho", content_hash="h1"
    )
    event = _event(db_session, item)
    keep = "https://keep.test/si"
    drop = "https://drop.test/no"
    llm = FakeStructuredLLM(
        {
            "ResearchQueries": ResearchQueries(queries=["q1"]),
            "RelevanceBatch": RelevanceBatch(
                hits=[
                    RelevanceHit(url=keep, classification=ResearchRelevance.SAME_EVENT),
                    RelevanceHit(url=drop, classification=ResearchRelevance.IRRELEVANT),
                ]
            ),
        }
    )
    search = FakeSearchProvider(
        [
            SearchHit(title="Sí", url=keep, snippet="mismo suceso"),
            SearchHit(title="No", url=drop, snippet="otra cosa"),
        ]
    )
    fetcher = RecordingFetcher()
    ResearchService(db_session, llm=llm, search=search, fetcher=fetcher).research(event.id, trigger="admin")
    assert fetcher.fetched == [keep]


def test_query_and_domain_caps(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(
        db_session, source.id, url="https://ejemplo.test/base", title="Base", body="Hecho", content_hash="h1"
    )
    event = _event(db_session, item)
    urls = [f"https://www.mismo.test/nota-{index}" for index in range(5)]
    llm = _llm([f"consulta {index}" for index in range(6)], urls)
    search = FakeSearchProvider(
        [SearchHit(title=f"Nota {index}", url=url, snippet="cobertura") for index, url in enumerate(urls)]
    )
    fetcher = RecordingFetcher()
    service = ResearchService(db_session, llm=llm, search=search, fetcher=fetcher)

    result = service.research(event.id, trigger="admin")

    assert len(search.queries) == 2
    assert all(query.count == 5 for query in search.queries)
    assert result["candidates"] == 3
    assert len(fetcher.fetched) == 3


def test_search_query_carries_freshness(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(
        db_session, source.id, url="https://ejemplo.test/base", title="Base", body="Hecho", content_hash="h1"
    )
    event = _event(db_session, item, started_at=datetime.now(timezone.utc) - timedelta(hours=3))
    llm = _llm(["q"], [])
    search = FakeSearchProvider([])
    ResearchService(db_session, llm=llm, search=search, fetcher=RecordingFetcher()).research(
        event.id, trigger="admin"
    )
    assert search.queries[0].freshness == "pd"


def test_running_lock_skips_providers(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(
        db_session, source.id, url="https://ejemplo.test/base", title="Base", body="Hecho", content_hash="h1"
    )
    event = _event(db_session, item)
    db_session.add(
        PipelineRun(event_id=event.id, stage="research", status=PipelineStatus.RUNNING, metadata_json={})
    )
    db_session.flush()
    llm = _llm(["q"], ["https://x.test/n"])
    search = FakeSearchProvider([SearchHit(title="x", url="https://x.test/n", snippet="x")])
    fetcher = RecordingFetcher()

    result = ResearchService(db_session, llm=llm, search=search, fetcher=fetcher).research(
        event.id, trigger="admin"
    )

    assert result["skipped"] is True
    assert result["reason"] == "already_running"
    assert llm.calls == []
    assert search.queries == []
    assert fetcher.fetched == []


def test_monitored_source_flags_are_not_mutated(db_session: Session) -> None:
    source = _source(
        db_session,
        name="Medio",
        domain="medio.test",
        homepage_url="https://medio.test",
        feed_url="https://medio.test/rss.xml",
        is_monitored=True,
        preferred_ingestion_method=IngestionMethod.RSS,
    )
    item = _item(
        db_session, source.id, url="https://medio.test/base", title="Base", body="Hecho", content_hash="h1"
    )
    event = _event(db_session, item)
    extra = "https://www.medio.test/extra"
    llm = _llm(["q"], [extra])
    search = FakeSearchProvider([SearchHit(title="Extra", url=extra, snippet="más datos")])
    ResearchService(db_session, llm=llm, search=search, fetcher=RecordingFetcher()).research(
        event.id, trigger="admin"
    )
    db_session.refresh(source)
    assert source.is_monitored is True
    assert source.is_enabled is True
    assert source.preferred_ingestion_method == IngestionMethod.RSS
    assert source.feed_url == "https://medio.test/rss.xml"


def test_published_event_status_is_not_degraded(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(
        db_session, source.id, url="https://ejemplo.test/base", title="Base", body="Hecho", content_hash="h1"
    )
    event = _event(db_session, item, status=EventStatus.PUBLISHED)
    url = "https://nuevo.test/nota"
    llm = _llm(["q"], [url])
    search = FakeSearchProvider([SearchHit(title="Nota", url=url, snippet="cobertura")])
    ResearchService(db_session, llm=llm, search=search, fetcher=RecordingFetcher()).research(
        event.id, trigger="admin"
    )
    db_session.refresh(event)
    assert event.status == EventStatus.PUBLISHED


def test_missing_search_provider_fails_pipeline(db_session: Session, monkeypatch) -> None:
    source = _source(db_session)
    item = _item(
        db_session, source.id, url="https://ejemplo.test/base", title="Base", body="Hecho", content_hash="h1"
    )
    event = _event(db_session, item)
    llm = _llm(["q"], [])

    def boom() -> None:
        raise ProviderNotConfiguredError("Falta BRAVE_API_KEY")

    monkeypatch.setattr("app.services.research_service.get_search_provider", boom)
    result = ResearchService(db_session, llm=llm, search=None).research(event.id, trigger="admin")
    assert result["error"]
    run = db_session.scalars(
        select(PipelineRun).where(PipelineRun.event_id == event.id, PipelineRun.stage == "research")
    ).one()
    assert run.status == PipelineStatus.FAILED


def test_research_ingest_does_not_call_detection(db_session: Session, monkeypatch) -> None:
    source = _source(db_session)
    item = _item(
        db_session, source.id, url="https://ejemplo.test/base", title="Base", body="Hecho", content_hash="h1"
    )
    event = _event(db_session, item)
    url = "https://nuevo.test/nota"
    llm = _llm(["q"], [url])
    search = FakeSearchProvider([SearchHit(title="Nota", url=url, snippet="cobertura")])

    def boom(*_args, **_kwargs):
        raise AssertionError("detect no debería correr")

    monkeypatch.setattr("app.services.detection_service.DetectionService.detect", boom)
    monkeypatch.setattr("app.workers.tasks.detect_event.delay", boom)
    ResearchService(db_session, llm=llm, search=search, fetcher=RecordingFetcher()).research(
        event.id, trigger="admin"
    )


def test_second_research_does_not_duplicate_links(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(
        db_session, source.id, url="https://ejemplo.test/base", title="Base", body="Hecho", content_hash="h1"
    )
    event = _event(db_session, item)
    url = "https://nuevo.test/nota"
    llm = _llm(["q"], [url])
    search = FakeSearchProvider([SearchHit(title="Nota", url=url, snippet="cobertura")])
    fetcher = RecordingFetcher()
    service = ResearchService(db_session, llm=llm, search=search, fetcher=fetcher)
    first = service.research(event.id, trigger="admin")
    second = service.research(event.id, trigger="admin")
    assert first["attached"] == 1
    assert second["attached"] == 0
    assert (
        db_session.scalar(
            select(func.count()).select_from(EventSource).where(EventSource.event_id == event.id)
        )
        == 2
    )


def test_detect_event_enqueues_research_when_created(monkeypatch) -> None:
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
        "app.workers.tasks.DetectionService",
        lambda session: SimpleNamespace(
            detect=lambda *_a, **_k: {"created": True, "event_id": "eid"}
        ),
    )
    monkeypatch.setattr("app.workers.tasks.research_event.delay", lambda *args: queued.append(args))
    monkeypatch.setattr("app.workers.tasks.allow_new_event_pipeline", lambda poll_id: True)
    from app.workers.tasks import detect_event

    detect_event.run("00000000-0000-0000-0000-000000000001", "poll-test")
    assert queued == [("eid", "new_event")]


def test_detect_event_does_not_enqueue_research_when_not_created(monkeypatch) -> None:
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
        "app.workers.tasks.DetectionService",
        lambda session: SimpleNamespace(
            detect=lambda *_a, **_k: {"created": False, "event_id": "eid"}
        ),
    )
    monkeypatch.setattr("app.workers.tasks.research_event.delay", lambda *args: queued.append(args))
    monkeypatch.setattr(
        "app.workers.tasks.allow_new_event_pipeline",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no debería consultar budget")),
    )
    from app.workers.tasks import detect_event

    detect_event.run("00000000-0000-0000-0000-000000000001", "poll-test")
    assert queued == []


def test_admin_research_unauthorized() -> None:
    with TestClient(app) as client:
        response = client.post(f"/api/v1/admin/events/{uuid4()}/research")
    assert response.status_code == 401


def test_admin_research_accepted(db_session: Session, monkeypatch) -> None:
    queued: list[tuple] = []
    monkeypatch.setattr("app.api.admin.research_event.delay", lambda *args: queued.append(args))
    source = _source(db_session)
    item = _item(
        db_session, source.id, url="https://ejemplo.test/base", title="Base", body="Hecho", content_hash="h1"
    )
    event = _event(db_session, item)
    db_session.commit()
    settings = get_settings()
    with TestClient(app) as client:
        login = client.post("/api/v1/admin/login", json={"password": settings.admin_password})
        assert login.status_code == 200
        response = client.post(f"/api/v1/admin/events/{event.id}/research")
    assert response.status_code == 202
    assert response.json()["queued"] is True
    assert queued == [(str(event.id), "admin")]


def test_admin_research_conflict_when_running(db_session: Session, monkeypatch) -> None:
    queued: list[tuple] = []
    monkeypatch.setattr("app.api.admin.research_event.delay", lambda *args: queued.append(args))
    source = _source(db_session)
    item = _item(
        db_session, source.id, url="https://ejemplo.test/base", title="Base", body="Hecho", content_hash="h1"
    )
    event = _event(db_session, item)
    db_session.add(
        PipelineRun(event_id=event.id, stage="research", status=PipelineStatus.RUNNING, metadata_json={})
    )
    db_session.commit()
    settings = get_settings()
    with TestClient(app) as client:
        client.post("/api/v1/admin/login", json={"password": settings.admin_password})
        response = client.post(f"/api/v1/admin/events/{event.id}/research")
    assert response.status_code == 409
    assert queued == []


def test_brave_always_sends_freshness(monkeypatch) -> None:
    captured: dict = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"web": {"results": [{"title": "t", "url": "https://a.test/n", "description": "d"}]}}

    class FakeClient:
        def __init__(self, timeout=None) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def get(self, url, params=None, headers=None):
            captured["params"] = params
            return FakeResponse()

    monkeypatch.setattr("app.providers.brave.httpx.Client", FakeClient)
    from app.providers.base import SearchQuery
    from app.providers.brave import BraveSearchProvider

    hits = BraveSearchProvider(api_key="k").search(SearchQuery(text="q", count=3))
    assert captured["params"]["freshness"] == "pw"
    assert hits[0].url == "https://a.test/n"


def test_code_queries_use_headline_locality_and_date(db_session: Session) -> None:
    from app.services.research_service import build_code_research_queries

    source = _source(db_session)
    item = _item(
        db_session, source.id, url="https://ejemplo.test/base", title="Base", body="Hecho", content_hash="h1"
    )
    event = _event(
        db_session,
        item,
        started_at=datetime(2026, 8, 23, tzinfo=timezone.utc),
    )
    queries = build_code_research_queries(event, entity_names=["colectivo"], limit=2)
    assert len(queries) == 2
    assert "Rosario" in queries[0]
    assert "Choque" in queries[0]
    assert "accidente" not in queries[0].casefold()
    assert "colectivo" in queries[1]
    assert "2026-08-23" in queries[1]


def test_code_queries_skip_locality_entity(db_session: Session) -> None:
    from app.services.research_service import build_code_research_queries

    source = _source(db_session)
    item = _item(
        db_session, source.id, url="https://ejemplo.test/base", title="Base", body="Hecho", content_hash="h2"
    )
    event = _event(
        db_session,
        item,
        started_at=datetime(2026, 8, 23, tzinfo=timezone.utc),
    )
    queries = build_code_research_queries(event, entity_names=["Rosario"], limit=2)
    assert queries
    assert all(query.casefold().strip() != "rosario" for query in queries)
    assert all("choque" in query.casefold() for query in queries)


def test_code_queries_drop_null_title_and_use_summary(db_session: Session) -> None:
    from app.services.research_service import build_code_research_queries

    source = _source(db_session)
    item = _item(
        db_session, source.id, url="https://ejemplo.test/festival", title="Festival", body="El Cruce", content_hash="n1"
    )
    event = _event(
        db_session,
        item,
        title_internal="null",
        event_type="protesta",
        short_summary="Se celebra la 25ª edición del Festival El Cruce en Rosario",
        started_at=datetime(2026, 8, 28, tzinfo=timezone.utc),
    )
    queries = build_code_research_queries(
        event,
        entity_names=["Festival Internacional de Artes Escénicas Contemporáneas El Cruce", "Rosario"],
        limit=2,
    )
    assert queries
    assert all("null" not in query.casefold() for query in queries)
    assert any("festival" in query.casefold() or "cruce" in query.casefold() for query in queries)


def test_null_title_without_facts_defers_to_llm(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(
        db_session, source.id, url="https://ejemplo.test/vacio", title="x", body="Hecho", content_hash="n2"
    )
    event = _event(
        db_session,
        item,
        title_internal="null",
        event_type="otro",
        short_summary="null",
        started_at=datetime(2026, 8, 28, tzinfo=timezone.utc),
    )
    llm = FakeStructuredLLM(
        {
            "ResearchQueries": ResearchQueries(queries=["Festival El Cruce Rosario septiembre"]),
            "RelevanceBatch": RelevanceBatch(hits=[]),
        }
    )
    result = ResearchService(
        db_session, llm=llm, search=FakeSearchProvider([]), fetcher=RecordingFetcher()
    ).research(event.id, trigger="new_event")
    assert result["query_source"] == "ultra"
    assert result["queries"] == ["Festival El Cruce Rosario septiembre"]
    assert "ResearchQueries" in llm.calls
    assert all("null" not in query for query in result["queries"])


def test_fluvial_is_not_same_event_as_pyme_forum(db_session: Session) -> None:
    from app.services.research_service import hit_conflicts_with_event

    source = _source(db_session)
    item = _item(
        db_session,
        source.id,
        url="https://ejemplo.test/foro",
        title="Foro PyME",
        body="El Concejo convocó el Foro PyME",
        content_hash="foro",
    )
    event = _event(
        db_session,
        item,
        title_internal="Se llevó a cabo el Foro PyME de Rosario en el Concejo Municipal",
        event_type="anuncio_oficial",
        short_summary="Foro de micro, pequeñas y medianas empresas en el Recinto de Sesiones",
    )
    url = "https://rosario3.test/fluvial"
    hit = SearchHit(
        title="Pullaro inauguró el nuevo muelle de La Fluvial",
        url=url,
        snippet="La obra demandó una inversión provincial de $2.690 millones",
    )
    assert hit_conflicts_with_event(event, hit) is True
    llm = FakeStructuredLLM(
        {
            "ResearchQueries": ResearchQueries(queries=["foro pyme rosario"]),
            "RelevanceBatch": RelevanceBatch(
                hits=[
                    RelevanceHit(url=url, classification=ResearchRelevance.SAME_EVENT, confidence=0.95)
                ]
            ),
        }
    )
    fetcher = RecordingFetcher()
    result = ResearchService(
        db_session,
        llm=llm,
        search=FakeSearchProvider([hit]),
        fetcher=fetcher,
    ).research(event.id, trigger="new_event")
    assert result["attached"] == 0
    assert result["relevance_demoted"] >= 1
    assert fetcher.fetched == []
    assert (
        db_session.scalar(
            select(func.count()).select_from(EventSource).where(EventSource.event_id == event.id)
        )
        == 1
    )


def test_murder_is_not_attached_to_festival(db_session: Session) -> None:
    from app.services.research_service import hit_conflicts_with_event

    source = _source(db_session)
    item = _item(
        db_session,
        source.id,
        url="https://ejemplo.test/festival",
        title="El Cruce",
        body="Festival de artes escénicas",
        content_hash="fest",
    )
    event = _event(
        db_session,
        item,
        title_internal="null",
        event_type="protesta",
        short_summary="Se celebra la 25ª edición del Festival Internacional El Cruce en Rosario",
    )
    url = "https://tn.com.ar/asesinato-barra"
    hit = SearchHit(
        title="Asesinaron a balazos a un exintegrante de la barra de Rosario Central",
        url=url,
        snippet="fue asesinado a balazos tras salir de prisión",
    )
    assert hit_conflicts_with_event(event, hit) is True
    llm = FakeStructuredLLM(
        {
            "ResearchQueries": ResearchQueries(queries=["festival el cruce rosario"]),
            "RelevanceBatch": RelevanceBatch(
                hits=[
                    RelevanceHit(url=url, classification=ResearchRelevance.SAME_EVENT, confidence=0.8)
                ]
            ),
        }
    )
    fetcher = RecordingFetcher()
    result = ResearchService(
        db_session, llm=llm, search=FakeSearchProvider([hit]), fetcher=fetcher
    ).research(event.id, trigger="new_event")
    assert result["attached"] == 0
    assert result["relevance_demoted"] >= 1
    assert fetcher.fetched == []


def test_different_event_is_not_attached(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(
        db_session, source.id, url="https://ejemplo.test/base", title="Base", body="Hecho", content_hash="h1"
    )
    event = _event(db_session, item)
    url = "https://sanluis.test/otro-choque"
    llm = FakeStructuredLLM(
        {
            "ResearchQueries": ResearchQueries(queries=["q"]),
            "RelevanceBatch": RelevanceBatch(
                hits=[
                    RelevanceHit(
                        url=url,
                        classification=ResearchRelevance.DIFFERENT_EVENT,
                        confidence=0.9,
                    )
                ]
            ),
        }
    )
    search = FakeSearchProvider(
        [SearchHit(title="Choque en San Luis", url=url, snippet="Otro choque en San Luis")]
    )
    fetcher = RecordingFetcher()
    result = ResearchService(db_session, llm=llm, search=search, fetcher=fetcher).research(
        event.id, trigger="new_event"
    )
    assert result["attached"] == 0
    assert fetcher.fetched == []
    assert (
        db_session.scalar(
            select(func.count()).select_from(EventSource).where(EventSource.event_id == event.id)
        )
        == 1
    )


def test_standard_source_cap_stops_at_four(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(
        db_session, source.id, url="https://ejemplo.test/base", title="Base", body="Hecho", content_hash="h1"
    )
    event = _event(db_session, item)
    urls = [f"https://medio{index}.test/nota" for index in range(5)]
    llm = _llm(["q"], urls)
    search = FakeSearchProvider(
        [SearchHit(title=f"Nota {index}", url=url, snippet="mismo choque") for index, url in enumerate(urls)]
    )
    result = ResearchService(
        db_session, llm=llm, search=search, fetcher=RecordingFetcher()
    ).research(event.id, trigger="new_event")
    assert result["attached"] == 3
    assert result["source_cap"] == 4
    assert result["escalated"] is False
    counted = db_session.scalar(
        select(func.count()).select_from(EventSource).where(
            EventSource.event_id == event.id,
            EventSource.relation_type.in_(
                [EventSourceRelation.INITIAL, EventSourceRelation.ADDITIONAL]
            ),
        )
    )
    assert counted == 4


def test_contradiction_allows_escalated_source_cap(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(
        db_session, source.id, url="https://ejemplo.test/base", title="Base", body="Hecho", content_hash="h1"
    )
    contra = _item(
        db_session,
        source.id,
        url="https://ejemplo.test/contra",
        title="Versión opuesta",
        body="Desmienten el choque",
        content_hash="hc",
    )
    event = _event(db_session, item)
    EventService(db_session).attach_source(
        event,
        contra.id,
        relation_type=EventSourceRelation.CONTRADICTING,
        is_primary=False,
    )
    urls = [f"https://medio{index}.test/nota" for index in range(10)]
    llm = FakeStructuredLLM(
        {
            "ResearchQueries": ResearchQueries(queries=["extra 3", "extra 4"]),
            "RelevanceBatch": RelevanceBatch(
                hits=[
                    RelevanceHit(url=url, classification=ResearchRelevance.SAME_EVENT)
                    for url in urls
                ]
            ),
        }
    )
    search = FakeSearchProvider(
        [SearchHit(title=f"Nota {index}", url=url, snippet="cobertura") for index, url in enumerate(urls)]
    )
    result = ResearchService(
        db_session, llm=llm, search=search, fetcher=RecordingFetcher()
    ).research(event.id, trigger="new_event")
    assert result["escalated"] is True
    assert result["source_cap"] == 8
    counted = db_session.scalar(
        select(func.count()).select_from(EventSource).where(
            EventSource.event_id == event.id,
            EventSource.relation_type.in_(
                [EventSourceRelation.INITIAL, EventSourceRelation.ADDITIONAL]
            ),
        )
    )
    assert counted == 8
    assert result["attached"] == 7
