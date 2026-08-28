from __future__ import annotations

from datetime import timedelta
from math import sqrt
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.clock import utc_now
from app.core.config import get_settings
from app.core.prompts import load_prompt
from app.core.text import normalize_name
from app.core.usage_context import update_usage_context, usage_scope
from app.domain.enums import EventSourceRelation, PipelineStatus, SourceItemStatus
from app.models import Entity, Event, EventEntity, PipelineRun, SourceItem
from app.models.event import EMBEDDING_DIMENSIONS
from app.providers.base import EmbeddingProvider, ProviderNotConfiguredError, StructuredLLMProvider
from app.providers.registry import (
    ModelRole,
    get_embedding_provider,
    get_structured_provider,
    get_structured_provider_optional,
)
from app.repositories import EntityRepository, EventRepository, PipelineRunRepository, SourceItemRepository
from app.schemas import EventCreate
from app.schemas.detection import DedupDecision, EventCandidate
from app.services.editorial_gate import evaluate_editorial_gate, needs_location_fallback
from app.services.event_service import EventService

# Reextraer con Luna solo si ultra falla el schema o la ubicación es poco confiable/contradictoria.
_EXTRACT_FALLBACK_ERRORS = (ValidationError, ValueError, KeyError, RuntimeError)


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    norm_l = sqrt(sum(a * a for a in left))
    norm_r = sqrt(sum(b * b for b in right))
    if norm_l == 0 or norm_r == 0:
        return 0.0
    return dot / (norm_l * norm_r)


def embedding_text(candidate: EventCandidate) -> str:
    parts = [
        candidate.event_type,
        candidate.what_happened,
        candidate.short_summary,
        candidate.locality or "",
        candidate.province or "",
        " ".join(entity.name for entity in candidate.entities),
    ]
    return ". ".join(part for part in parts if part)


class DetectionService:
    def __init__(
        self,
        session: Session,
        *,
        ultra_llm: StructuredLLMProvider | None = None,
        light_llm: StructuredLLMProvider | None = None,
        dedup_llm: StructuredLLMProvider | None = None,
        embeddings: EmbeddingProvider | None = None,
    ) -> None:
        self.session = session
        self.settings = get_settings()
        self.items = SourceItemRepository(session)
        self.events = EventRepository(session)
        self.entities = EntityRepository(session)
        self.pipeline = PipelineRunRepository(session)
        self.event_service = EventService(session)
        self.ultra_llm = ultra_llm
        self.light_llm = light_llm
        self.dedup_llm = dedup_llm
        self.embeddings = embeddings

    def detect(self, source_item_id: UUID, *, attempt: int = 1) -> dict:
        item = self.items.get(source_item_id)
        if item is None:
            raise ValueError("source_item_not_found")

        existing_link = self.events.get_link_for_item(item.id)
        if existing_link is not None and item.processing_status != SourceItemStatus.PENDING:
            item.processing_status = SourceItemStatus.PROCESSED
            return {"event_id": str(existing_link.event_id), "created": False, "reason": "already_linked"}

        run = PipelineRun(
            source_item_id=item.id,
            stage="event_detection",
            status=PipelineStatus.RUNNING,
            attempt=attempt,
        )
        self.pipeline.add(run)
        self.session.flush()
        item.processing_status = SourceItemStatus.PROCESSING

        try:
            with usage_scope(
                stage="event_detection",
                source_item_id=item.id,
                pipeline_run_id=run.id,
            ):
                candidate, extract_meta = self._extract_candidate(item)
                gate = evaluate_editorial_gate(candidate)
                if not gate.allowed:
                    item.processing_status = SourceItemStatus.SKIPPED
                    run.status = PipelineStatus.SUCCESS
                    run.finished_at = utc_now()
                    run.metadata_json = {
                        **extract_meta,
                        "filtered": True,
                        "filter_reason": gate.reason,
                        "editorial_scope": gate.editorial_scope.value,
                        "editorial_reason": candidate.editorial_reason,
                        "locality": candidate.locality,
                        "province": candidate.province,
                        "country_code": candidate.country_code,
                        "location_confidence": candidate.location_confidence,
                        "what_happened": candidate.what_happened,
                    }
                    self.session.flush()
                    return {
                        "event_id": None,
                        "created": False,
                        "filtered": True,
                        "reason": gate.reason,
                    }
                event, created, reason = self._resolve_event(item, candidate)
                update_usage_context(event_id=event.id)
                self._persist_entities(event, candidate)
                self._store_embedding(event, candidate)
                item.processing_status = SourceItemStatus.PROCESSED
                run.status = PipelineStatus.SUCCESS
                run.event_id = event.id
                run.finished_at = utc_now()
                run.metadata_json = {**extract_meta, "reason": reason, "created": created}
                self.session.flush()
                return {"event_id": str(event.id), "created": created, "reason": reason}
        except ProviderNotConfiguredError as exc:
            return self._fail(item.id, attempt, str(exc))
        except Exception as exc:
            if _is_transient(exc):
                self.session.rollback()
                item = self.items.get(source_item_id)
                if item is not None:
                    item.processing_status = SourceItemStatus.PENDING
                    self.pipeline.add(
                        PipelineRun(
                            source_item_id=item.id,
                            stage="event_detection",
                            status=PipelineStatus.RETRY,
                            attempt=attempt,
                            error_message=str(exc),
                            finished_at=utc_now(),
                        )
                    )
                    self.session.flush()
                raise
            return self._fail(item.id, attempt, str(exc))

    def _fail(self, source_item_id: UUID, attempt: int, message: str) -> dict:
        self.session.rollback()
        item = self.items.get(source_item_id)
        if item is None:
            return {"event_id": None, "created": False, "reason": "failed", "error": message}
        item.processing_status = SourceItemStatus.FAILED
        self.pipeline.add(
            PipelineRun(
                source_item_id=item.id,
                stage="event_detection",
                status=PipelineStatus.FAILED,
                attempt=attempt,
                error_message=message,
                finished_at=utc_now(),
            )
        )
        self.session.flush()
        return {"event_id": None, "created": False, "reason": "failed", "error": message}

    def _extract_candidate(self, item: SourceItem) -> tuple[EventCandidate, dict]:
        body = item.clean_text or item.raw_text or item.title or item.url
        user_prompt = (
            f"Título: {item.title or ''}\n"
            f"URL: {item.url}\n"
            f"Publicado: {item.published_at or ''}\n\n"
            f"{body[:8000]}"
        )
        system_prompt = load_prompt("event_extraction.md")
        ultra = self.ultra_llm
        light = self.light_llm
        if ultra is None and light is None:
            ultra = get_structured_provider_optional(ModelRole.ULTRA_LIGHT_PROCESSING)

        def _light() -> StructuredLLMProvider:
            nonlocal light
            if light is None:
                light = get_structured_provider(ModelRole.LIGHT_PROCESSING)
            return light

        def _call(llm: StructuredLLMProvider) -> EventCandidate:
            return llm.generate_structured(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                schema=EventCandidate,
            )

        if ultra is None:
            return _call(_light()), {}

        try:
            candidate = _call(ultra)
        except ProviderNotConfiguredError:
            raise
        except Exception as exc:
            candidate = _call(_light())
            reason = (
                "invalid_schema"
                if isinstance(exc, _EXTRACT_FALLBACK_ERRORS)
                else "ultra_error"
            )
            return candidate, {
                "fallback_from": ModelRole.ULTRA_LIGHT_PROCESSING.value,
                "fallback_to": ModelRole.LIGHT_PROCESSING.value,
                "fallback_reason": reason,
                "ultra_error": str(exc)[:300],
            }

        if needs_location_fallback(candidate):
            candidate = _call(_light())
            return candidate, {
                "fallback_from": ModelRole.ULTRA_LIGHT_PROCESSING.value,
                "fallback_to": ModelRole.LIGHT_PROCESSING.value,
                "fallback_reason": "low_location_confidence",
            }
        return candidate, {}

    def _resolve_event(
        self,
        item: SourceItem,
        candidate: EventCandidate,
    ) -> tuple[Event, bool, str]:
        url = item.canonical_url or item.url
        by_url = self.events.find_by_url(url)
        if by_url is not None:
            self.event_service.attach_source(
                by_url,
                item.id,
                relation_type=EventSourceRelation.CONFIRMING,
                is_primary=False,
            )
            return by_url, False, "level1_url"

        window_start = utc_now() - timedelta(hours=self.settings.event_match_window_hours)
        event_type = candidate.event_type if candidate.event_type not in {"unknown", ""} else None
        recent = self.events.list_match_candidates(
            since=window_start,
            event_type=event_type,
            locality=candidate.locality,
        )
        if not recent:
            recent = self.events.list_match_candidates(since=window_start)

        code_match = self._level1_match(candidate, recent)
        if code_match is not None:
            self.event_service.attach_source(
                code_match,
                item.id,
                relation_type=EventSourceRelation.CONFIRMING,
                is_primary=False,
            )
            return code_match, False, "level1_code"

        scored = self._score_embeddings(candidate, recent)
        high = self.settings.event_match_high_threshold
        low = self.settings.event_match_low_threshold
        if scored:
            best_event, best_score = scored[0]
            if best_score >= high:
                self.event_service.attach_source(
                    best_event,
                    item.id,
                    relation_type=EventSourceRelation.CONFIRMING,
                    is_primary=False,
                )
                return best_event, False, f"embedding_high:{best_score:.3f}"
            if low <= best_score < high:
                decision = self._ask_terra(candidate, scored[:5])
                if decision.decision == "EXISTING_EVENT" and decision.event_id:
                    existing = self.events.get(decision.event_id)
                    if existing is not None:
                        self.event_service.attach_source(
                            existing,
                            item.id,
                            relation_type=EventSourceRelation.CONFIRMING,
                            is_primary=False,
                        )
                        return existing, False, "terra_existing"
                event = self._create_event(item, candidate)
                return event, True, "terra_new"
            event = self._create_event(item, candidate)
            return event, True, f"embedding_low:{best_score:.3f}"

        event = self._create_event(item, candidate)
        return event, True, "no_candidates"

    def _level1_match(self, candidate: EventCandidate, recent: list[Event]) -> Event | None:
        if (
            candidate.occurred_at is None
            or not candidate.event_type
            or candidate.event_type == "unknown"
            or not candidate.locality
        ):
            return None

        candidate_names = {normalize_name(entity.name) for entity in candidate.entities if entity.name}
        if not candidate_names:
            return None

        candidate_day = candidate.occurred_at.date()

        for event in recent:
            if (
                event.started_at is None
                or not event.event_type
                or event.event_type == "unknown"
                or not event.locality
            ):
                continue
            if candidate_day != event.started_at.date():
                continue
            if candidate.event_type != event.event_type:
                continue
            if candidate.locality.lower() != event.locality.lower():
                continue

            event_names = {entity.normalized_name for entity in self.entities.list_for_event(event.id)}
            shared_entities = candidate_names & event_names
            # Same day + type + locality is not enough; entity overlap is vs
            # list_for_event, never against the event title.
            if len(shared_entities) >= 2:
                return event
        return None

    def _score_embeddings(
        self,
        candidate: EventCandidate,
        recent: list[Event],
    ) -> list[tuple[Event, float]]:
        if not recent:
            return []
        embedder = self.embeddings or get_embedding_provider()
        query = embedder.embed([embedding_text(candidate)])[0]
        scored: list[tuple[Event, float]] = []
        missing: list[Event] = []
        cached: list[tuple[Event, list[float]]] = []
        for event in recent:
            row = self.events.get_embedding(event.id)
            if row is None:
                missing.append(event)
            else:
                cached.append((event, list(row.embedding)))
        if missing:
            texts = [
                f"{event.event_type}. {event.title_internal}. {event.short_summary or ''}"
                for event in missing
            ]
            vectors = embedder.embed(texts)
            for event, vector in zip(missing, vectors, strict=True):
                self.events.upsert_embedding(event.id, vector, embedder.model)
                cached.append((event, vector))
        for event, vector in cached:
            scored.append((event, cosine_similarity(query, vector)))
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored

    def _ask_terra(self, candidate: EventCandidate, scored: list[tuple[Event, float]]) -> DedupDecision:
        llm = self.dedup_llm or get_structured_provider(ModelRole.AMBIGUOUS_DEDUP)
        lines = [
            f"Candidato: {candidate.model_dump_json()}",
            "Eventos existentes:",
        ]
        for event, score in scored:
            lines.append(
                f"- id={event.id} type={event.event_type} score={score:.3f} "
                f"title={event.title_internal} place={event.locality} summary={event.short_summary}"
            )
        return llm.generate_structured(
            system_prompt=load_prompt("deduplication.md"),
            user_prompt="\n".join(lines),
            schema=DedupDecision,
        )

    def _create_event(self, item: SourceItem, candidate: EventCandidate) -> Event:
        return self.event_service.create(
            EventCreate(
                title_internal=candidate.what_happened[:500],
                event_type=candidate.event_type or "unknown",
                source_item_id=item.id,
                started_at=candidate.occurred_at,
                country_code=candidate.country_code or "AR",
                province=candidate.province,
                locality=candidate.locality,
                neighborhood=candidate.neighborhood,
                address_text=candidate.address_text,
                latitude=candidate.latitude,
                longitude=candidate.longitude,
                short_summary=candidate.short_summary,
            )
        )

    def _persist_entities(self, event: Event, candidate: EventCandidate) -> None:
        linked = {
            (entity.normalized_name, entity.entity_type): entity
            for entity in self.entities.list_for_event(event.id)
        }
        existing_roles = {
            (row.entity_id, row.role)
            for row in self.session.scalars(
                select(EventEntity).where(EventEntity.event_id == event.id)
            ).all()
        }
        for extracted in candidate.entities:
            normalized = normalize_name(extracted.name)
            if not normalized:
                continue
            key = (normalized, extracted.entity_type)
            entity = linked.get(key)
            if entity is None:
                entity = Entity(
                    name=extracted.name.strip(),
                    normalized_name=normalized,
                    entity_type=extracted.entity_type,
                )
                self.entities.add(entity)
                self.session.flush()
                linked[key] = entity
            role = (extracted.role or "mencionado")[:64]
            if (entity.id, role) in existing_roles:
                continue
            try:
                with self.session.begin_nested():
                    self.events.add_entity_link(
                        EventEntity(event_id=event.id, entity_id=entity.id, role=role)
                    )
                    self.session.flush()
                existing_roles.add((entity.id, role))
            except IntegrityError:
                continue

    def _store_embedding(self, event: Event, candidate: EventCandidate) -> None:
        embedder = self.embeddings or get_embedding_provider()
        if self.events.get_embedding(event.id) is not None:
            return
        vector = embedder.embed([embedding_text(candidate)])[0]
        if len(vector) != EMBEDDING_DIMENSIONS:
            raise ValueError(
                f"El embedding tiene dimensión {len(vector)}, se esperaba {EMBEDDING_DIMENSIONS}"
            )
        self.events.upsert_embedding(event.id, vector, embedder.model)
        self.session.flush()


def _is_transient(exc: BaseException) -> bool:
    name = type(exc).__name__
    text = str(exc).lower()
    if "timeout" in text or "429" in text or "503" in text or "502" in text:
        return True
    return name in {"ConnectError", "TimeoutException", "ReadTimeout", "TransportError", "HTTPStatusError"}
