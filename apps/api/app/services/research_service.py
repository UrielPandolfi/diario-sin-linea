from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import timedelta
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.clock import utc_now
from app.core.config import get_settings
from app.core.prompts import load_prompt
from app.core.text import content_fingerprint
from app.core.urls import canonicalize_url, url_domain
from app.core.usage_context import usage_scope
from app.domain.enums import EventSourceRelation, IngestionMethod, PipelineStatus
from app.models import Entity, Event, EventEntity, EventSource, PipelineRun, Source, SourceItem
from app.providers.base import (
    ProviderNotConfiguredError,
    SearchHit,
    SearchProvider,
    SearchQuery,
    StructuredLLMProvider,
)
from app.providers.registry import (
    ModelRole,
    get_search_provider,
    get_structured_provider,
    get_structured_provider_optional,
)
from app.repositories import (
    EventRepository,
    PipelineRunRepository,
    SourceItemRepository,
    SourceRepository,
)
from app.schemas import SourceCreate, SourceItemCreate
from app.schemas.research import RelevanceBatch, ResearchQueries, ResearchRelevance
from app.services.event_service import EventService
from app.services.fetching import HttpFetcher, extract_text
from app.services.source_item_service import SourceItemService
from app.services.source_service import SourceService

RESEARCH_STAGE = "research"
_ATTACH_RELATIONS = (EventSourceRelation.INITIAL, EventSourceRelation.ADDITIONAL)
_LLM_FALLBACK_ERRORS = (ValidationError, ValueError, KeyError, RuntimeError)
_AMBIGUOUS_RELEVANCE_MIN = 0.4
_AMBIGUOUS_RELEVANCE_MAX = 0.6
_ESCALATE_TRIGGERS = {"contradiction", "conflict", "conflict_found", "claims_uncertain"}


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


def build_code_research_queries(
    event: Event,
    *,
    entity_names: Sequence[str] = (),
    limit: int = 2,
) -> list[str]:
    """1–2 consultas desde tipo, entidades, localidad y fecha. Sin LLM."""
    when = event.started_at or event.detected_at
    date_part = when.strftime("%Y-%m-%d") if when is not None else ""
    locality = (event.locality or "").strip()
    event_type = (event.event_type or "").strip()
    if event_type.casefold() in {"unknown", "otro", ""}:
        event_type = ""
    names = [name.strip() for name in entity_names if name and name.strip()]
    headline = (event.title_internal or "").strip()
    queries: list[str] = []

    def add(text: str) -> None:
        compact = " ".join(text.split())
        if not compact:
            return
        folded = compact.casefold()
        if any(folded == existing.casefold() for existing in queries):
            return
        queries.append(compact)

    def join_unique(*parts: str) -> str:
        seen: list[str] = []
        for part in parts:
            token = " ".join(part.split())
            if not token:
                continue
            folded = token.casefold()
            if any(folded == item.casefold() or folded in item.casefold() for item in seen):
                continue
            seen.append(token)
        return " ".join(seen)

    add(join_unique(event_type, locality, date_part))
    entity = names[0] if names else ""
    add(join_unique(entity or headline, locality))
    return queries[:limit]


def relevance_needs_fallback(batch: RelevanceBatch) -> bool:
    for hit in batch.hits:
        if hit.confidence is None:
            continue
        if _AMBIGUOUS_RELEVANCE_MIN <= hit.confidence <= _AMBIGUOUS_RELEVANCE_MAX:
            return True
    return False


class ResearchService:
    def __init__(
        self,
        session: Session,
        *,
        llm: StructuredLLMProvider | None = None,
        ultra_llm: StructuredLLMProvider | None = None,
        light_llm: StructuredLLMProvider | None = None,
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
        self.ultra_llm = ultra_llm
        self.light_llm = light_llm
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
            with usage_scope(
                stage=RESEARCH_STAGE,
                event_id=event.id,
                pipeline_run_id=run.id,
            ):
                result = self._run(event, freshness, trigger=trigger)
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

    def _ultra(self) -> StructuredLLMProvider:
        return (
            self.ultra_llm
            or self.llm
            or get_structured_provider_optional(ModelRole.ULTRA_LIGHT_PROCESSING)
            or get_structured_provider(ModelRole.LIGHT_PROCESSING)
        )

    def _light(self) -> StructuredLLMProvider:
        return self.light_llm or self.llm or get_structured_provider(ModelRole.LIGHT_PROCESSING)

    def _run(self, event: Event, freshness: str, *, trigger: str) -> dict:
        search = self.search or get_search_provider()
        max_per_query = self.settings.max_research_results_per_query
        max_per_domain = self.settings.max_research_results_per_domain
        links = self._event_source_rows(event.id)
        escalate = self._should_escalate_research(trigger, links)
        query_target = (
            self.settings.max_research_queries_per_event
            if escalate
            else self.settings.initial_research_queries
        )
        source_cap = (
            self.settings.max_escalated_event_sources
            if escalate
            else self.settings.max_standard_event_sources
        )

        entity_names = self._entity_names(event.id)
        queries = build_code_research_queries(
            event, entity_names=entity_names, limit=query_target
        )
        query_source = "code"
        if len(queries) < query_target:
            extra = self._complete_queries(event, queries, query_target)
            queries = extra
            query_source = "code+ultra"
        queries = queries[:query_target]
        if not queries:
            return {
                "queries": [],
                "attached": 0,
                "fetched": 0,
                "reused": 0,
                "query_source": query_source,
                "escalated": escalate,
                "source_cap": source_cap,
            }

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
                "query_source": query_source,
                "escalated": escalate,
                "source_cap": source_cap,
            }

        same_event_urls, relevance_counts, relevance_fallback = self._same_event_urls(
            event, candidates
        )
        attached = 0
        fetched = 0
        reused = 0
        fetch_log: list[str] = []
        counted = self._counted_source_count(event.id)
        for hit in candidates:
            if counted >= source_cap:
                break
            canonical = canonicalize_url(hit.url)
            if canonical not in same_event_urls and hit.url not in same_event_urls:
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
                    counted += 1
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
                counted += 1
                linked.add(canonical)

        return {
            "queries": queries,
            "attached": attached,
            "fetched": fetched,
            "reused": reused,
            "candidates": len(candidates),
            "fetched_urls": fetch_log,
            "query_source": query_source,
            "escalated": escalate,
            "source_cap": source_cap,
            "relevance": relevance_counts,
            "relevance_fallback": relevance_fallback,
        }

    def _complete_queries(
        self,
        event: Event,
        current: list[str],
        target: int,
    ) -> list[str]:
        needed = max(0, target - len(current))
        if needed == 0:
            return current
        prompt = self._event_prompt(event, needed)
        if current:
            prompt += "\nYa tenemos:\n" + "\n".join(f"- {query}" for query in current)
        batch = self._generate_structured(
            system_prompt=load_prompt("research_queries.md"),
            user_prompt=prompt,
            schema=ResearchQueries,
        )
        queries = list(current)
        seen = {query.casefold() for query in queries}
        for raw in batch.queries:
            text = " ".join((raw or "").split())
            if not text or text.casefold() in seen:
                continue
            queries.append(text)
            seen.add(text.casefold())
            if len(queries) >= target:
                break
        return queries

    def _same_event_urls(
        self,
        event: Event,
        candidates: list[SearchHit],
    ) -> tuple[set[str], dict[str, int], bool]:
        batch, used_fallback = self._classify_relevance(event, candidates)
        counts = {item.value: 0 for item in ResearchRelevance}
        chosen: set[str] = set()
        for hit in batch.hits:
            counts[hit.classification.value] = counts.get(hit.classification.value, 0) + 1
            if hit.classification == ResearchRelevance.SAME_EVENT:
                chosen.add(canonicalize_url(hit.url))
                chosen.add(hit.url)
        return chosen, counts, used_fallback

    def _classify_relevance(
        self,
        event: Event,
        candidates: list[SearchHit],
    ) -> tuple[RelevanceBatch, bool]:
        ultra = self._ultra()
        light = self._light()
        user_prompt = self._relevance_prompt(event, candidates)
        system_prompt = load_prompt("research_relevance.md")
        try:
            batch = ultra.generate_structured(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                schema=RelevanceBatch,
            )
        except ProviderNotConfiguredError:
            raise
        except _LLM_FALLBACK_ERRORS:
            if light is ultra:
                raise
            batch = light.generate_structured(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                schema=RelevanceBatch,
            )
            return batch, True
        if relevance_needs_fallback(batch) and light is not ultra:
            batch = light.generate_structured(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                schema=RelevanceBatch,
            )
            return batch, True
        return batch, False

    def _generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema: type,
    ):
        ultra = self._ultra()
        light = self._light()
        try:
            return ultra.generate_structured(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                schema=schema,
            )
        except ProviderNotConfiguredError:
            raise
        except _LLM_FALLBACK_ERRORS:
            if light is ultra:
                raise
            return light.generate_structured(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                schema=schema,
            )

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

    def _relevance_prompt(self, event: Event, candidates: list[SearchHit]) -> str:
        lines = [self._event_prompt(event, 0), "Resultados:"]
        for hit in candidates:
            lines.append(f"- url={hit.url} title={hit.title} snippet={hit.snippet or ''}")
        return "\n".join(lines)

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

    def _event_source_rows(self, event_id: UUID) -> list[EventSource]:
        return list(
            self.session.scalars(select(EventSource).where(EventSource.event_id == event_id))
        )

    def _counted_source_count(self, event_id: UUID) -> int:
        value = self.session.scalar(
            select(func.count())
            .select_from(EventSource)
            .where(
                EventSource.event_id == event_id,
                EventSource.relation_type.in_(_ATTACH_RELATIONS),
            )
        )
        return int(value or 0)

    def _entity_names(self, event_id: UUID) -> list[str]:
        stmt = (
            select(Entity.name)
            .join(EventEntity, EventEntity.entity_id == Entity.id)
            .where(EventEntity.event_id == event_id)
        )
        names: list[str] = []
        seen: set[str] = set()
        for name in self.session.scalars(stmt):
            if not name or name.casefold() in seen:
                continue
            seen.add(name.casefold())
            names.append(name)
        return names

    def _should_escalate_research(self, trigger: str, links: list[EventSource]) -> bool:
        if trigger in _ESCALATE_TRIGGERS:
            return True
        if any(link.relation_type == EventSourceRelation.CONTRADICTING for link in links):
            return True
        if links and not any(link.is_primary for link in links):
            return True
        return False
