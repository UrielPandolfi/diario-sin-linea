from datetime import datetime, timezone

import httpx
import pytest
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.domain.enums import IngestionMethod
from app.providers.base import ProviderNotConfiguredError, SearchHit, SearchQuery
from app.providers.brave import BraveSearchProvider
from app.providers.exa import ExaSearchProvider, normalize_exa_results
from app.providers.fakes import FakeStructuredLLM, RecordingFetcher
from app.providers.registry import get_search_provider
from app.schemas import EventCreate, SourceCreate, SourceItemCreate
from app.schemas.research import RelevanceBatch, RelevanceHit, ResearchQueries
from app.services.event_service import EventService
from app.services.research_service import ResearchService
from app.services.source_item_service import SourceItemService
from app.services.source_service import SourceService


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_normalize_exa_valid_response() -> None:
    hits = normalize_exa_results(
        {
            "results": [
                {
                    "title": "Choque en Pellegrini",
                    "url": "https://medio.test/nota",
                    "highlights": ["Dos colectivos chocaron", "hay heridos"],
                    "publishedDate": "2026-08-24",
                },
                {"title": "Sin URL", "highlights": ["x"]},
                "ignorar",
            ]
        }
    )
    assert len(hits) == 1
    assert hits[0] == SearchHit(
        title="Choque en Pellegrini",
        url="https://medio.test/nota",
        snippet="Dos colectivos chocaron hay heridos",
    )


def test_normalize_exa_empty_results() -> None:
    assert normalize_exa_results({"results": []}) == []
    assert normalize_exa_results({}) == []


def test_normalize_exa_invalid_payload() -> None:
    with pytest.raises(ValueError, match="objeto JSON"):
        normalize_exa_results([])
    with pytest.raises(ValueError, match="results no es una lista"):
        normalize_exa_results({"results": {"url": "https://x.test"}})


def test_exa_search_sends_query_and_limit(monkeypatch) -> None:
    captured: dict = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "results": [
                    {"title": "A", "url": "https://a.test/1", "highlights": ["snip"]},
                    {"title": "B", "url": "https://b.test/2", "text": "cuerpo largo"},
                ]
            }

    class FakeClient:
        def __init__(self, timeout=None) -> None:
            captured["timeout"] = timeout

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def post(self, url, json=None, headers=None):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return FakeResponse()

    monkeypatch.setattr("app.providers.exa.httpx.Client", FakeClient)
    hits = ExaSearchProvider(api_key="secret-key").search(
        SearchQuery(text="choque colectivos rosario", count=3, freshness="pw")
    )
    assert captured["url"] == "https://api.exa.ai/search"
    assert captured["headers"]["Authorization"] == "Bearer secret-key"
    assert captured["json"]["query"] == "choque colectivos rosario"
    assert captured["json"]["numResults"] == 3
    assert captured["json"]["type"] == "auto"
    assert captured["json"]["contents"] == {"highlights": True}
    assert "startPublishedDate" in captured["json"]
    assert len(hits) == 2
    assert hits[0].snippet == "snip"
    assert hits[1].snippet == "cuerpo largo"


def test_exa_search_clamps_num_results(monkeypatch) -> None:
    captured: dict = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"results": []}

    class FakeClient:
        def __init__(self, timeout=None) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def post(self, url, json=None, headers=None):
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr("app.providers.exa.httpx.Client", FakeClient)
    ExaSearchProvider(api_key="k").search(SearchQuery(text="q", count=500))
    assert captured["json"]["numResults"] == 100
    ExaSearchProvider(api_key="k").search(SearchQuery(text="q", count=0))
    assert captured["json"]["numResults"] == 1


def test_exa_search_maps_since_until(monkeypatch) -> None:
    captured: dict = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"results": []}

    class FakeClient:
        def __init__(self, timeout=None) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def post(self, url, json=None, headers=None):
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr("app.providers.exa.httpx.Client", FakeClient)
    ExaSearchProvider(api_key="k").search(
        SearchQuery(
            text="q",
            count=2,
            since=datetime(2026, 8, 1, tzinfo=timezone.utc),
            until=datetime(2026, 8, 20, tzinfo=timezone.utc),
        )
    )
    assert captured["json"]["startPublishedDate"] == "2026-08-01"
    assert captured["json"]["endPublishedDate"] == "2026-08-20"


def test_exa_http_error_propagates(monkeypatch) -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            raise httpx.HTTPStatusError(
                "429",
                request=httpx.Request("POST", "https://api.exa.ai/search"),
                response=httpx.Response(429),
            )

        def json(self) -> dict:
            return {}

    class FakeClient:
        def __init__(self, timeout=None) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def post(self, url, json=None, headers=None):
            return FakeResponse()

    monkeypatch.setattr("app.providers.exa.httpx.Client", FakeClient)
    with pytest.raises(httpx.HTTPStatusError):
        ExaSearchProvider(api_key="k").search(SearchQuery(text="q", count=1))


def test_exa_invalid_json_body(monkeypatch) -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            raise ValueError("no json")

    class FakeClient:
        def __init__(self, timeout=None) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def post(self, url, json=None, headers=None):
            return FakeResponse()

    monkeypatch.setattr("app.providers.exa.httpx.Client", FakeClient)
    with pytest.raises(ValueError, match="JSON no parseable"):
        ExaSearchProvider(api_key="k").search(SearchQuery(text="q", count=1))


def test_registry_exa_requires_key(monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "search_provider", "exa")
    monkeypatch.setattr(settings, "exa_api_key", None)
    with pytest.raises(ProviderNotConfiguredError, match="EXA_API_KEY"):
        get_search_provider()


def test_registry_exa_returns_exa_provider(monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "search_provider", "exa")
    monkeypatch.setattr(settings, "exa_api_key", "exa-test-key")
    provider = get_search_provider()
    assert isinstance(provider, ExaSearchProvider)
    assert provider.api_key == "exa-test-key"


def test_registry_brave_still_works(monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "search_provider", "brave")
    monkeypatch.setattr(settings, "brave_api_key", "brave-test-key")
    provider = get_search_provider()
    assert isinstance(provider, BraveSearchProvider)
    assert provider.api_key == "brave-test-key"


def test_registry_unknown_provider(monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "search_provider", "serpapi")
    with pytest.raises(ProviderNotConfiguredError, match="no soportado"):
        get_search_provider()


def test_research_uses_injected_exa_normalized_hits(db_session: Session, monkeypatch) -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "results": [
                    {
                        "title": "Seis heridos",
                        "url": "https://b.test/seis-heridos",
                        "highlights": ["El choque dejó seis heridos"],
                    }
                ]
            }

    class FakeClient:
        def __init__(self, timeout=None) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def post(self, url, json=None, headers=None):
            return FakeResponse()

    monkeypatch.setattr("app.providers.exa.httpx.Client", FakeClient)
    source = SourceService(db_session).create(
        SourceCreate(
            name="Fuente A",
            preferred_ingestion_method=IngestionMethod.RSS,
            feed_url="https://a.test/rss.xml",
            is_monitored=True,
            is_enabled=True,
        )
    )
    item = SourceItemService(db_session).ingest(
        SourceItemCreate(
            source_id=source.id,
            url="https://a.test/choque",
            canonical_url="https://a.test/choque",
            content_hash="ha-exa",
            title="Choque",
            clean_text="Dos colectivos chocaron en Pellegrini.",
        )
    ).item
    event = EventService(db_session).create(
        EventCreate(
            title_internal="Choque Pellegrini",
            event_type="accidente",
            source_item_id=item.id,
            started_at=datetime.now(timezone.utc),
            locality="Rosario",
            province="Santa Fe",
            short_summary="Choque de colectivos",
        )
    )
    llm = FakeStructuredLLM(
        {
            "ResearchQueries": ResearchQueries(queries=["choque colectivos rosario"]),
            "RelevanceBatch": RelevanceBatch(
                hits=[RelevanceHit(url="https://b.test/seis-heridos", relevant=True)]
            ),
        }
    )
    fetcher = RecordingFetcher(
        {"https://b.test/seis-heridos": "<article><p>El choque dejó seis heridos.</p></article>"}
    )
    result = ResearchService(
        db_session,
        llm=llm,
        search=ExaSearchProvider(api_key="test"),
        fetcher=fetcher,
    ).research(event.id, trigger="test")
    assert result.get("skipped") is False
    assert result.get("attached", 0) >= 1
    assert "https://b.test/seis-heridos" in fetcher.fetched
