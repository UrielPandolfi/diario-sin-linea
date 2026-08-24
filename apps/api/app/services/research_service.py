from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.clock import utc_now
from app.core.config import get_settings
from app.core.prompts import load_prompt
from app.core.text import content_fingerprint
from app.core.urls import canonicalize_url, url_domain
from app.domain.enums import EventSourceRelation, IngestionMethod, PipelineStatus
from app.models import Event, PipelineRun, Source, SourceItem
from app.providers.base import (
    ProviderNotConfiguredError,
    SearchHit,
    SearchProvider,
    SearchQuery,
    StructuredLLMProvider,
)
from app.providers.registry import ModelRole, get_search_provider, get_structured_provider
from app.repositories import (
    EventRepository,
    PipelineRunRepository,
    SourceItemRepository,
    SourceRepository,
)
from app.schemas import SourceCreate, SourceItemCreate
from app.schemas.research import RelevanceBatch, ResearchQueries
from app.services.event_service import EventService
from app.services.fetching import HttpFetcher, extract_text
from app.services.source_item_service import SourceItemService
from app.services.source_service import SourceService

RESEARCH_STAGE = "research"


def freshness_for_event(event: Event) -> str:
    when = event.started_at or event.detected_at
    if when is None:
        return "pw"
    now = utc_now()
    if when.tzinfo is None:
        age = now.replace(tzinfo=None) - when
    else:
        age = now - when
    if age <= timedelta(days=1):
        return "pd"
    if age <= timedelta(days=7):
        return "pw"
    if age <= timedelta(days=31):
        return "pm"
    return "py"


class ResearchService:
    def __init__(
        self,
        session: Session,
        *,
        llm: StructuredLLMProvider | None = None,
        search: SearchProvider | None = None,
        fetcher: HttpFetcher | None = None,
        extract: Callable[[str, str], str | None] = extract_text,
    ) -> None:
        self.session = session
        self.settings = get_settings()
        self.events = EventRepository(session)
        self.items = SourceItemRepository(session)
        self.sources = SourceRepository(session)
        self.pipeline = PipelineRunRepository(session)
        self.event_service = EventService(session)
        self.source_service = SourceService(session)
        self.item_service = SourceItemService(session)
        self.llm = llm
        self.search = search
        self.fetcher = fetcher or HttpFetcher()
        self.extract = extract

    def research(self, event_id: UUID, *, trigger: str, context: dict | None = None) -> dict:
        event = self.events.get(event_id)
        if event is None:
            raise ValueError("event_not_found")
        original_status = event.status

        if self.pipeline.get_running(event_id, RESEARCH_STAGE) is not None:
            return {
                "skipped": True,
                "reason": "already_running",
                "event_id": str(event_id),
                "attached": 0,
            }

        freshness = freshness_for_event(event)
        run = PipelineRun(
            event_id=event.id,
            stage=RESEARCH_STAGE,
            status=PipelineStatus.RUNNING,
            metadata_json={
                "trigger": trigger,
                "context": context or {},
                "freshness": freshness,
            },
        )
        self.pipeline.add(run)
        try:
            with self.session.begin_nested():
                self.session.flush()
        except IntegrityError:
            self.session.expunge(run)
            return {
                "skipped": True,
                "reason": "already_running",
                "event_id": str(event_id),
                "attached": 0,
            }

        try:
            result = self._run(event, freshness)
            run.status = PipelineStatus.SUCCESS
            run.finished_at = utc_now()
            run.metadata_json = {**(run.metadata_json or {}), **result}
            event.status = original_status
            self.session.flush()
            return {"skipped": False, "event_id": str(event.id), **result}
        except ProviderNotConfiguredError as exc:
            return self._fail(run, event, original_status, str(exc))
        except Exception as exc:
            return self._fail(run, event, original_status, str(exc))

    def _fail(self, run: PipelineRun, event: Event, original_status: Any, message: str) -> dict:
        run.status = PipelineStatus.FAILED
        run.error_message = message
        run.finished_at = utc_now()
        event.status = original_status
        self.session.flush()
        return {
            "skipped": False,
            "event_id": str(event.id),
            "attached": 0,
            "error": message,
        }

    def _run(self, event: Event, freshness: str) -> dict:
        llm = self.llm or get_structured_provider(ModelRole.LIGHT_PROCESSING)
        search = self.search or get_search_provider()
        max_queries = self.settings.max_research_queries_per_event
        max_per_query = self.settings.max_research_results_per_query
        max_per_domain = self.settings.max_research_results_per_domain

        queries = llm.generate_structured(
            system_prompt=load_prompt("research_queries.md"),
            user_prompt=self._event_prompt(event, max_queries),
            schema=ResearchQueries,
        ).queries[:max_queries]
        if not queries:
            return {"queries": [], "attached": 0, "fetched": 0, "reused": 0}

        hits: list[SearchHit] = []
        for text in queries:
            hits.extend(
                search.search(SearchQuery(text=text, count=max_per_query, freshness=freshness))
            )

        linked = self.events.canonical_urls_for_event(event.id)
        candidates = self._prefilter(hits, linked, max_per_domain)
        if not candidates:
            return {
                "queries": queries,
                "attached": 0,
                "fetched": 0,
                "reused": 0,
                "candidates": 0,
            }

        relevant_urls = self._relevant_urls(llm, event, candidates)
        attached = 0
        fetched = 0
        reused = 0
        fetch_log: list[str] = []
        for hit in candidates:
            canonical = canonicalize_url(hit.url)
            if canonical not in relevant_urls and hit.url not in relevant_urls:
                continue
            if canonical in linked or hit.url in linked:
                continue
            existing = self.items.get_by_canonical_url(canonical) or self.items.get_by_canonical_url(
                hit.url
            )
            if existing is not None:
                _, created_link = self.event_service.attach_source(
                    event,
                    existing.id,
                    relation_type=EventSourceRelation.ADDITIONAL,
                    is_primary=False,
                )
                if created_link:
                    attached += 1
                    reused += 1
                    linked.add(canonical)
                continue
            item = self._ingest_new(hit, canonical, fetch_log)
            if item is None:
                continue
            fetched += 1
            _, created_link = self.event_service.attach_source(
                event,
                item.id,
                relation_type=EventSourceRelation.ADDITIONAL,
                is_primary=False,
            )
            if created_link:
                attached += 1
                linked.add(canonical)

        return {
            "queries": queries,
            "attached": attached,
            "fetched": fetched,
            "reused": reused,
            "candidates": len(candidates),
            "fetched_urls": fetch_log,
        }

    def _event_prompt(self, event: Event, max_queries: int) -> str:
        when = event.started_at or event.detected_at
        return (
            f"Máximo {max_queries} consultas.\n"
            f"Título interno: {event.title_internal}\n"
            f"Tipo: {event.event_type}\n"
            f"Resumen: {event.short_summary or ''}\n"
            f"Lugar: {event.locality or ''} {event.province or ''}\n"
            f"Fecha: {when}\n"
        )

    def _prefilter(
        self,
        hits: list[SearchHit],
        linked: set[str],
        max_per_domain: int,
    ) -> list[SearchHit]:
        seen_urls: set[str] = set()
        per_domain: dict[str, int] = {}
        selected: list[SearchHit] = []
        for hit in hits:
            if not hit.url:
                continue
            canonical = canonicalize_url(hit.url)
            if canonical in seen_urls or hit.url in seen_urls:
                continue
            if canonical in linked or hit.url in linked:
                continue
            domain = url_domain(canonical)
            if not domain:
                continue
            if per_domain.get(domain, 0) >= max_per_domain:
                continue
            per_domain[domain] = per_domain.get(domain, 0) + 1
            seen_urls.add(canonical)
            selected.append(hit)
        return selected

    def _relevant_urls(
        self,
        llm: StructuredLLMProvider,
        event: Event,
        candidates: list[SearchHit],
    ) -> set[str]:
        lines = [self._event_prompt(event, 0), "Resultados:"]
        for hit in candidates:
            lines.append(f"- url={hit.url} title={hit.title} snippet={hit.snippet or ''}")
        batch = llm.generate_structured(
            system_prompt=load_prompt("research_relevance.md"),
            user_prompt="\n".join(lines),
            schema=RelevanceBatch,
        )
        chosen = {canonicalize_url(item.url) for item in batch.hits if item.relevant}
        chosen.update(item.url for item in batch.hits if item.relevant)
        return chosen

    def _ingest_new(self, hit: SearchHit, canonical: str, fetch_log: list[str]) -> SourceItem | None:
        try:
            fetched = self.fetcher.fetch(hit.url)
            fetch_log.append(hit.url)
        except Exception:
            fetch_log.append(f"fail:{hit.url}")
            return None
        html = fetched.body or ""
        final_url = fetched.url or hit.url
        canonical = canonicalize_url(final_url) or canonical
        text = self.extract(html, final_url) or hit.snippet or hit.title
        domain = url_domain(canonical)
        source = self._source_for_domain(domain, canonical)
        fingerprint = content_fingerprint(title=hit.title, body=text)
        outcome = self.item_service.ingest(
            SourceItemCreate(
                source_id=source.id,
                url=final_url,
                canonical_url=canonical,
                content_hash=fingerprint,
                title=hit.title or None,
                raw_text=html[:20000] if html else None,
                clean_text=text,
                excerpt=(hit.snippet or text or "")[:500] or None,
            )
        )
        return outcome.item

    def _source_for_domain(self, domain: str, url: str) -> Source:
        existing = self.sources.get_by_domain(domain) if domain else None
        if existing is not None:
            return existing
        return self.source_service.create(
            SourceCreate(
                name=domain or url,
                domain=domain or None,
                homepage_url=f"https://{domain}" if domain else url,
                preferred_ingestion_method=IngestionMethod.UNKNOWN,
                is_monitored=False,
                is_enabled=True,
            )
        )
