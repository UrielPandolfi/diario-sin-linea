from uuid import UUID

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.text import content_fingerprint
from app.domain.enums import IngestionMethod, SourceItemStatus
from app.schemas import SourceCreate
from app.services.app_settings import AppSettingsService
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


def _rss_feed(count: int, *, dated: bool = False) -> str:
    items: list[str] = []
    for index in range(1, count + 1):
        pub = f"<pubDate>Wed, 16 Sep 2026 {index:02d}:00:00 GMT</pubDate>" if dated else ""
        items.append(
            f"""    <item>
      <title>Nota {index}</title>
      <link>https://www.ejemplo.test/nota-{index}</link>
      <guid>guid-nota-{index}</guid>
      <description>Resumen {index}.</description>
      {pub}
    </item>"""
        )
    joined = "\n".join(items)
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<rss version=\"2.0\"><channel>\n"
        "<title>Fuente de prueba</title>\n"
        f"{joined}\n"
        "</channel></rss>\n"
    )


def _feed_pages(xml: str, count: int) -> dict[str, FetchResult]:
    pages = {
        FEED_URL: FetchResult(url=FEED_URL, body=xml, content_type="application/rss+xml"),
    }
    for index in range(1, count + 1):
        url = f"https://www.ejemplo.test/nota-{index}"
        pages[url] = FetchResult(url=url, body=ARTICLE_HTML, content_type="text/html")
    return pages


def _article_calls(fetcher: FakeFetcher) -> list[str]:
    return [url for url in fetcher.calls if url != FEED_URL]


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
    meta = db_session.execute(text("SELECT metadata_json FROM source_items")).scalar_one()
    assert meta["body_source"] == "extracted_html"
    assert meta["fetch_ok"] is True


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
    meta = db_session.execute(text("SELECT metadata_json FROM source_items")).scalar_one()
    assert meta["body_source"] == "rss_summary"
    assert meta["fetch_ok"] is False
    assert meta.get("fetch_error")


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


def test_poll_source_task_enqueues_detection_after_commit(monkeypatch) -> None:
    from uuid import uuid4

    events: list[str] = []
    item_a = uuid4()
    item_b = uuid4()

    class Sess:
        def commit(self) -> None:
            events.append("commit")

        def rollback(self) -> None:
            pass

        def close(self) -> None:
            pass

    class FakeIngestion:
        def __init__(self, session, **_kwargs) -> None:
            assert "enqueue_detection" not in _kwargs or _kwargs.get("enqueue_detection") is None

        def poll_source(self, source_id):
            events.append("poll")
            return type(
                "R",
                (),
                {
                    "skipped": False,
                    "created": 2,
                    "updated": 0,
                    "seen": 2,
                    "reason": None,
                    "item_ids": [item_a, item_b],
                },
            )()

    monkeypatch.setattr("app.workers.tasks.SessionLocal", Sess)
    monkeypatch.setattr("app.workers.tasks.IngestionService", FakeIngestion)
    monkeypatch.setattr(
        "app.workers.tasks._enqueue_detection",
        lambda item_id, poll_id: events.append(f"enqueue:{item_id}"),
    )
    from app.workers.tasks import poll_source

    result = poll_source.run(str(uuid4()))
    assert events[:2] == ["poll", "commit"]
    assert events[2:] == [f"enqueue:{item_a}", f"enqueue:{item_b}"]
    assert result["created"] == 2
    assert result["detection_queued"] == 2
    assert result["poll_id"]


def test_poll_source_task_caps_detection_enqueue(monkeypatch) -> None:
    from uuid import uuid4

    events: list[str] = []
    item_a = uuid4()
    item_b = uuid4()
    item_c = uuid4()
    settings = get_settings()
    monkeypatch.setattr(settings, "max_new_events_per_poll", 1)

    class Sess:
        def commit(self) -> None:
            events.append("commit")

        def rollback(self) -> None:
            pass

        def close(self) -> None:
            pass

    class FakeIngestion:
        def __init__(self, session, **_kwargs) -> None:
            return None

        def poll_source(self, source_id):
            events.append("poll")
            return type(
                "R",
                (),
                {
                    "skipped": False,
                    "created": 3,
                    "updated": 0,
                    "seen": 3,
                    "reason": None,
                    "item_ids": [item_a, item_b, item_c],
                },
            )()

    monkeypatch.setattr("app.workers.tasks.SessionLocal", Sess)
    monkeypatch.setattr("app.workers.tasks.IngestionService", FakeIngestion)
    monkeypatch.setattr(
        "app.workers.tasks._enqueue_detection",
        lambda item_id, poll_id: events.append(f"enqueue:{item_id}"),
    )
    from app.workers.tasks import poll_source

    result = poll_source.run(str(uuid4()))
    assert events[2:] == [f"enqueue:{item_a}"]
    assert result["detection_queued"] == 1
    assert result["item_ids"] == [str(item_a), str(item_b), str(item_c)]


def test_poll_limit_caps_candidates_before_article_fetch(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "monitored_source_poll_limit", 5)
    source = _source(db_session)
    queued: list[UUID] = []
    fetcher = FakeFetcher(_feed_pages(_rss_feed(15), 15))
    result = _service(db_session, fetcher, queued).poll_source(source.id)

    assert result.skipped is False
    assert result.seen == 5
    assert result.created == 5
    assert len(queued) == 5
    assert _article_calls(fetcher) == [
        f"https://www.ejemplo.test/nota-{index}" for index in range(1, 6)
    ]
    count = db_session.execute(text("SELECT count(*) FROM source_items")).scalar_one()
    assert count == 5


def test_capped_poll_is_idempotent(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "monitored_source_poll_limit", 5)
    source = _source(db_session)
    queued: list[UUID] = []
    fetcher = FakeFetcher(_feed_pages(_rss_feed(15), 15))
    service = _service(db_session, fetcher, queued)

    first = service.poll_source(source.id)
    second = service.poll_source(source.id)

    assert first.created == 5
    assert second.created == 0
    assert second.updated == 0
    assert second.seen == 5
    assert len(queued) == 5
    count = db_session.execute(text("SELECT count(*) FROM source_items")).scalar_one()
    assert count == 5


def test_dated_feed_selects_newest_entries(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "monitored_source_poll_limit", 5)
    source = _source(db_session)
    queued: list[UUID] = []
    fetcher = FakeFetcher(_feed_pages(_rss_feed(15, dated=True), 15))
    result = _service(db_session, fetcher, queued).poll_source(source.id)

    assert result.created == 5
    titles = set(
        db_session.execute(text("SELECT title FROM source_items")).scalars().all()
    )
    assert titles == {f"Nota {index}" for index in range(11, 16)}
    assert _article_calls(fetcher) == [
        f"https://www.ejemplo.test/nota-{index}" for index in range(15, 10, -1)
    ]


def test_disabled_source_is_not_polled(db_session: Session) -> None:
    source = _source(db_session, is_enabled=False)
    fetcher = FakeFetcher({})
    service = IngestionService(db_session, fetcher=fetcher, extract=lambda html, url: "no")

    result = service.poll_source(source.id)

    assert result.skipped is True
    assert result.reason == "not_pollable"
    assert fetcher.calls == []
    assert db_session.execute(text("SELECT count(*) FROM source_items")).scalar_one() == 0


def test_poll_monitored_isolates_source_failures(db_session: Session) -> None:
    good = _source(db_session, name="Buena", domain="bueno.test")
    bad = _source(
        db_session,
        name="Rota",
        domain="roto.test",
        feed_url="https://www.roto.test/rss.xml",
    )
    queued: list[UUID] = []
    fetcher = FakeFetcher(
        {
            FEED_URL: FetchResult(url=FEED_URL, body=RSS_XML, content_type="application/rss+xml"),
            ARTICLE_URL: FetchResult(url=ARTICLE_URL, body=ARTICLE_HTML, content_type="text/html"),
        }
    )

    results = _service(db_session, fetcher, queued).poll_monitored()
    by_id = dict(results)

    assert by_id[good.id].created == 1
    assert isinstance(by_id[bad.id], Exception)
    assert len(queued) == 1
    assert good.last_success_at is not None
    assert good.failure_count == 0
    assert bad.last_failure_at is not None
    assert bad.failure_count == 1
    assert db_session.execute(text("SELECT count(*) FROM source_items")).scalar_one() == 1


def test_poll_monitored_sources_enqueues_only_pollable(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    watched = _source(db_session, name="Vigilada", domain="vigilada.test")
    extra = _source(db_session, name="Otra vigilada", domain="otra.test", feed_url="https://otra.test/rss.xml")
    _source(db_session, name="No vigilada", domain="novig.test", is_monitored=False)
    _source(db_session, name="Apagada", domain="apagada.test", is_enabled=False)
    db_session.flush()

    class _KeepOpen:
        def close(self) -> None:
            return None

        def __getattr__(self, name: str):
            return getattr(db_session, name)

    delayed: list[str] = []
    monkeypatch.setattr("app.workers.tasks.SessionLocal", lambda: _KeepOpen())
    monkeypatch.setattr(
        "app.workers.tasks.poll_source.delay",
        lambda source_id: delayed.append(source_id),
    )
    from app.workers.tasks import poll_monitored_sources

    result = poll_monitored_sources.run()
    assert result == {"queued": 2}
    assert set(delayed) == {str(watched.id), str(extra.id)}


def test_poll_monitored_sources_skips_when_auto_poll_disabled(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _source(db_session, name="Vigilada", domain="vigilada.test")
    AppSettingsService(db_session).set_auto_poll_enabled(False)
    db_session.flush()

    class _KeepOpen:
        def close(self) -> None:
            return None

        def __getattr__(self, name: str):
            return getattr(db_session, name)

    delayed: list[str] = []
    monkeypatch.setattr("app.workers.tasks.SessionLocal", lambda: _KeepOpen())
    monkeypatch.setattr(
        "app.workers.tasks.poll_source.delay",
        lambda source_id: delayed.append(source_id),
    )
    from app.workers.tasks import poll_monitored_sources

    result = poll_monitored_sources.run()
    assert result == {"queued": 0, "skipped": True, "reason": "auto_poll_disabled"}
    assert delayed == []


def test_manual_poll_still_runs_when_auto_poll_disabled(db_session: Session) -> None:
    AppSettingsService(db_session).set_auto_poll_enabled(False)
    source = _source(db_session)
    queued: list[UUID] = []
    fetcher = FakeFetcher(
        {
            FEED_URL: FetchResult(url=FEED_URL, body=RSS_XML, content_type="application/rss+xml"),
            ARTICLE_URL: FetchResult(url=ARTICLE_URL, body=ARTICLE_HTML, content_type="text/html"),
        }
    )
    result = _service(db_session, fetcher, queued).poll_source(source.id)

    assert result.created == 1
    assert len(queued) == 1


def test_beat_schedule_registers_poll_monitored_sources() -> None:
    from datetime import timedelta

    from app.workers.celery_app import celery_app

    entry = celery_app.conf.beat_schedule["poll-monitored-sources"]
    assert entry["task"] == "app.workers.tasks.poll_monitored_sources"
    assert entry["schedule"] == timedelta(
        seconds=get_settings().monitored_source_poll_interval_seconds
    )
