from uuid import UUID

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.text import content_fingerprint
from app.domain.enums import IngestionMethod, SourceItemStatus
from app.schemas import SourceCreate
from app.services.fetching import FetchResult
from app.services.ingestion_service import IngestionService
from app.services.source_service import SourceService


RSS_XML = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0">
  <channel>
    <title>Fuente de prueba</title>
    <item>
      <title>Choque en Pellegrini</title>
      <link>https://www.ejemplo.test/choque-pellegrini?utm_source=rss</link>
      <guid>guid-choque-1</guid>
      <description>Un colectivo chocó en Pellegrini y Corrientes.</description>
    </item>
  </channel>
</rss>
"""

ARTICLE_HTML = "<html><body><article><p>Cuerpo HTML que no debe extraerse de verdad.</p></article></body></html>"
FEED_URL = "https://www.ejemplo.test/rss.xml"
ARTICLE_URL = "https://www.ejemplo.test/choque-pellegrini?utm_source=rss"
EXTRACTED = "Cuerpo extraído de prueba"


class FakeFetcher:
    def __init__(self, pages: dict[str, FetchResult]) -> None:
        self.pages = pages
        self.calls: list[str] = []

    def fetch(self, url: str, *, timeout: float = 20.0) -> FetchResult:
        self.calls.append(url)
        if url not in self.pages:
            raise httpx.HTTPError(f"URL no mockeada: {url}")
        return self.pages[url]


def _source(session: Session, **overrides):
    payload = {
        "name": "Ejemplo RSS",
        "preferred_ingestion_method": IngestionMethod.RSS,
        "feed_url": FEED_URL,
        "is_monitored": True,
        "is_enabled": True,
    }
    payload.update(overrides)
    return SourceService(session).create(SourceCreate(**payload))


def _service(session: Session, fetcher: FakeFetcher, queued: list[UUID], extract=None) -> IngestionService:
    return IngestionService(
        session,
        fetcher=fetcher,
        extract=extract or (lambda html, url: EXTRACTED),
        enqueue_detection=queued.append,
    )


def test_rss_poll_creates_item_with_content_hash(db_session: Session) -> None:
    source = _source(db_session)
    queued: list[UUID] = []
    fetcher = FakeFetcher(
        {
            FEED_URL: FetchResult(url=FEED_URL, body=RSS_XML, content_type="application/rss+xml"),
            ARTICLE_URL: FetchResult(url=ARTICLE_URL, body=ARTICLE_HTML, content_type="text/html"),
        }
    )
    result = _service(db_session, fetcher, queued).poll_source(source.id)

    assert result.skipped is False
    assert result.created == 1
    assert result.seen == 1
    assert len(queued) == 1
    row = db_session.execute(
        text("SELECT content_hash, external_id, canonical_url, clean_text, processing_status FROM source_items")
    ).one()
    assert row.content_hash == content_fingerprint(title="Choque en Pellegrini", body=EXTRACTED)
    assert row.external_id == "guid-choque-1"
    assert row.canonical_url == "https://www.ejemplo.test/choque-pellegrini"
    assert row.clean_text == EXTRACTED
    assert row.processing_status == SourceItemStatus.PENDING.value
    assert source.last_success_at is not None


def test_second_poll_is_idempotent(db_session: Session) -> None:
    source = _source(db_session)
    queued: list[UUID] = []
    fetcher = FakeFetcher(
        {
            FEED_URL: FetchResult(url=FEED_URL, body=RSS_XML, content_type="application/rss+xml"),
            ARTICLE_URL: FetchResult(url=ARTICLE_URL, body=ARTICLE_HTML, content_type="text/html"),
        }
    )
    service = _service(db_session, fetcher, queued, extract=lambda html, url: "cuerpo")

    first = service.poll_source(source.id)
    second = service.poll_source(source.id)

    assert first.created == 1
    assert second.created == 0
    assert second.updated == 0
    assert second.seen == 1
    assert len(queued) == 1
    count = db_session.execute(text("SELECT count(*) FROM source_items")).scalar_one()
    assert count == 1


def test_same_publication_content_change_updates_without_duplicate(db_session: Session) -> None:
    source = _source(db_session)
    queued: list[UUID] = []
    extracted = {"text": "Cuerpo inicial del artículo"}
    fetcher = FakeFetcher(
        {
            FEED_URL: FetchResult(url=FEED_URL, body=RSS_XML, content_type="application/rss+xml"),
            ARTICLE_URL: FetchResult(url=ARTICLE_URL, body=ARTICLE_HTML, content_type="text/html"),
        }
    )
    service = _service(db_session, fetcher, queued, extract=lambda html, url: extracted["text"])

    first = service.poll_source(source.id)
    extracted["text"] = "Cuerpo actualizado con más detalle sobre el choque"
    second = service.poll_source(source.id)

    assert first.created == 1
    assert second.created == 0
    assert second.updated == 1
    assert len(queued) == 2
    count = db_session.execute(text("SELECT count(*) FROM source_items")).scalar_one()
    assert count == 1
    row = db_session.execute(text("SELECT content_hash, clean_text FROM source_items")).one()
    assert row.clean_text == extracted["text"]
    assert row.content_hash == content_fingerprint(title="Choque en Pellegrini", body=extracted["text"])


def test_unmonitored_source_is_not_polled(db_session: Session) -> None:
    source = _source(db_session, is_monitored=False)
    fetcher = FakeFetcher({})
    service = IngestionService(db_session, fetcher=fetcher, extract=lambda html, url: "no")

    result = service.poll_source(source.id)

    assert result.skipped is True
    assert fetcher.calls == []
    assert db_session.execute(text("SELECT count(*) FROM source_items")).scalar_one() == 0


def test_article_fetch_failure_still_persists_item(db_session: Session) -> None:
    source = _source(db_session)
    fetcher = FakeFetcher(
        {FEED_URL: FetchResult(url=FEED_URL, body=RSS_XML, content_type="application/rss+xml")}
    )
    service = IngestionService(db_session, fetcher=fetcher, extract=lambda html, url: None)

    result = service.poll_source(source.id)

    assert result.created == 1
    title = db_session.execute(text("SELECT title FROM source_items")).scalar_one()
    assert title == "Choque en Pellegrini"


def test_html_without_discovery_strategy_is_not_supported(db_session: Session) -> None:
    source = _source(
        db_session,
        preferred_ingestion_method=IngestionMethod.HTML,
        feed_url=None,
        homepage_url="https://www.ejemplo.test/",
    )
    fetcher = FakeFetcher({})
    service = IngestionService(db_session, fetcher=fetcher, extract=lambda html, url: "no")

    with pytest.raises(RuntimeError, match="estrategia explícita"):
        service.poll_source(source.id)

    assert fetcher.calls == []
    assert db_session.execute(text("SELECT count(*) FROM source_items")).scalar_one() == 0
    assert source.last_failure_at is not None
