from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from time import struct_time
from urllib.parse import urljoin
from uuid import UUID

import feedparser
from sqlalchemy.orm import Session

from app.core.clock import utc_now
from app.core.text import content_fingerprint
from app.core.urls import canonicalize_url
from app.core.source_content import (
    BODY_SOURCE_EXTRACTED_HTML,
    BODY_SOURCE_RSS_SUMMARY,
    BODY_SOURCE_TITLE_ONLY,
    is_extracted_body,
    merge_item_metadata,
)
from app.domain.enums import IngestionMethod, SourceItemStatus
from app.models import Source
from app.repositories import SourceRepository
from app.schemas import SourceItemCreate
from app.services.fetching import HttpFetcher, extract_text, fetch_failure_reason
from app.services.source_item_service import IngestOutcome, SourceItemService

EnqueueDetection = Callable[[UUID], None]


@dataclass
class FeedEntry:
    url: str
    title: str | None = None
    summary: str | None = None
    author: str | None = None
    external_id: str | None = None
    published_at: datetime | None = None


@dataclass
class PollResult:
    skipped: bool
    created: int = 0
    updated: int = 0
    seen: int = 0
    item_ids: list[UUID] = field(default_factory=list)
    reason: str | None = None


def _struct_time_to_datetime(value: struct_time | None) -> datetime | None:
    if value is None:
        return None
    return datetime(*value[:6], tzinfo=timezone.utc)


def _looks_like_feed(body: str, content_type: str) -> bool:
    lowered = content_type.lower()
    if "xml" in lowered or "rss" in lowered or "atom" in lowered:
        return True
    head = body.lstrip()[:400].lower()
    return head.startswith("<?xml") or "<rss" in head or "<feed" in head


class IngestionService:
    def __init__(
        self,
        session: Session,
        *,
        fetcher: HttpFetcher | None = None,
        extract: Callable[[str, str], str | None] = extract_text,
        enqueue_detection: EnqueueDetection | None = None,
    ) -> None:
        self.session = session
        self.sources = SourceRepository(session)
        self.item_service = SourceItemService(session)
        self.fetcher = fetcher or HttpFetcher()
        self.extract = extract
        self.enqueue_detection = enqueue_detection

    def poll_source(self, source_id: UUID) -> PollResult:
        source = self.sources.get(source_id)
        if source is None:
            raise ValueError("source_not_found")
        if not (source.is_monitored and source.is_enabled):
            return PollResult(skipped=True, reason="not_pollable")

        try:
            entries = self._collect_entries(source)
            changed_ids: list[UUID] = []
            created = 0
            updated = 0
            for entry in entries:
                outcome = self._ingest_entry(source, entry)
                if outcome.created or outcome.updated:
                    changed_ids.append(outcome.item.id)
                    if outcome.created:
                        created += 1
                    else:
                        updated += 1
                    if self.enqueue_detection is not None:
                        self.enqueue_detection(outcome.item.id)
            source.last_success_at = utc_now()
            source.failure_count = 0
            self.session.flush()
            return PollResult(
                skipped=False,
                created=created,
                updated=updated,
                seen=len(entries),
                item_ids=changed_ids,
            )
        except Exception:
            source.last_failure_at = utc_now()
            source.failure_count = (source.failure_count or 0) + 1
            self.session.flush()
            raise

    def poll_monitored(self) -> list[tuple[UUID, PollResult | Exception]]:
        results: list[tuple[UUID, PollResult | Exception]] = []
        for source in self.sources.list_pollable():
            try:
                results.append((source.id, self.poll_source(source.id)))
            except Exception as exc:  # noqa: BLE001 — isolate per source
                results.append((source.id, exc))
        return results

    def _collect_entries(self, source: Source) -> list[FeedEntry]:
        method = source.preferred_ingestion_method
        if method == IngestionMethod.RSS:
            if not source.feed_url:
                raise RuntimeError("La fuente RSS no tiene feed_url")
            fetched = self.fetcher.fetch(source.feed_url)
            return self._entries_from_feed(fetched.body, source.feed_url)
        if method == IngestionMethod.API:
            if not source.endpoint_url:
                raise RuntimeError("La fuente API no tiene endpoint_url")
            fetched = self.fetcher.fetch(source.endpoint_url)
            if _looks_like_feed(fetched.body, fetched.content_type):
                return self._entries_from_feed(fetched.body, source.endpoint_url)
            raise RuntimeError("endpoint_url no devolvió un feed RSS/Atom")
        if method == IngestionMethod.HTML:
            raise RuntimeError(
                "HTML/HTTP no está soportado: no hay una estrategia explícita "
                "de descubrimiento de URLs de artículos. Usá RSS."
            )
        raise RuntimeError(f"Método de ingesta no soportado: {method}")

    def _entries_from_feed(self, body: str, feed_url: str) -> list[FeedEntry]:
        parsed = feedparser.parse(body)
        entries: list[FeedEntry] = []
        for raw in parsed.entries[:50]:
            link = raw.get("link") or raw.get("id")
            if not link:
                continue
            fetch_url = urljoin(feed_url, str(link))
            entries.append(
                FeedEntry(
                    url=fetch_url,
                    title=raw.get("title"),
                    summary=raw.get("summary") or raw.get("description"),
                    author=raw.get("author"),
                    external_id=str(raw.get("id")) if raw.get("id") else None,
                    published_at=_struct_time_to_datetime(raw.get("published_parsed")),
                )
            )
        return entries

    def _ingest_entry(self, source: Source, entry: FeedEntry) -> IngestOutcome:
        canonical = canonicalize_url(entry.url)
        raw_text = entry.summary
        clean_text = entry.summary
        fetch_ok = False
        fetch_error = None
        body_source = BODY_SOURCE_TITLE_ONLY
        try:
            article = self.fetcher.fetch(entry.url)
            extracted = self.extract(article.body, article.url)
            raw_text = article.body
            fetch_ok = True
            if is_extracted_body(extracted, entry.title):
                clean_text = extracted
                body_source = BODY_SOURCE_EXTRACTED_HTML
            elif is_extracted_body(entry.summary, entry.title):
                clean_text = entry.summary
                body_source = BODY_SOURCE_RSS_SUMMARY
            else:
                clean_text = extracted or entry.summary
                body_source = BODY_SOURCE_TITLE_ONLY
        except Exception as exc:
            raw_text = entry.summary
            clean_text = entry.summary
            fetch_ok = False
            fetch_error = fetch_failure_reason(exc)
            if is_extracted_body(entry.summary, entry.title):
                body_source = BODY_SOURCE_RSS_SUMMARY
            else:
                body_source = BODY_SOURCE_TITLE_ONLY

        payload = SourceItemCreate(
            source_id=source.id,
            url=entry.url,
            content_hash=content_fingerprint(title=entry.title, body=clean_text),
            external_id=entry.external_id,
            canonical_url=canonical,
            title=entry.title,
            raw_text=raw_text,
            clean_text=clean_text,
            excerpt=(clean_text or entry.summary or "")[:500] or None,
            author=entry.author,
            published_at=entry.published_at,
            processing_status=SourceItemStatus.PENDING,
        )
        outcome = self.item_service.ingest(payload)
        if outcome.created or outcome.updated:
            merge_item_metadata(
                outcome.item,
                body_source=body_source,
                fetch_ok=fetch_ok,
                fetch_error=fetch_error,
            )
        return outcome
