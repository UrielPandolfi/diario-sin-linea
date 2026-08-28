from datetime import datetime
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Article,
    ArticleVersion,
    Claim,
    Entity,
    Event,
    EventEmbedding,
    EventEntity,
    EventSource,
    LlmUsage,
    PipelineRun,
    Source,
    SourceItem,
)
from app.domain.enums import EntityType, PipelineStatus, SourceItemStatus


class SourceRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, source: Source) -> Source:
        self.session.add(source)
        return source

    def get(self, source_id: UUID) -> Source | None:
        return self.session.get(Source, source_id)

    def list_all(self) -> list[Source]:
        stmt = select(Source).order_by(Source.name)
        return list(self.session.scalars(stmt))

    def list_pollable(self) -> list[Source]:
        stmt = select(Source).where(Source.is_monitored.is_(True), Source.is_enabled.is_(True))
        return list(self.session.scalars(stmt))

    def count_monitored(self) -> int:
        stmt = select(Source).where(Source.is_monitored.is_(True), Source.is_enabled.is_(True))
        return len(list(self.session.scalars(stmt)))

    def get_by_domain(self, domain: str) -> Source | None:
        stmt = select(Source).where(Source.domain == domain)
        return self.session.scalars(stmt).first()


class SourceItemRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, item: SourceItem) -> SourceItem:
        self.session.add(item)
        return item

    def get(self, item_id: UUID) -> SourceItem | None:
        return self.session.get(SourceItem, item_id)

    def get_by_source_and_hash(self, source_id: UUID, content_hash: str) -> SourceItem | None:
        stmt = select(SourceItem).where(
            SourceItem.source_id == source_id,
            SourceItem.content_hash == content_hash,
        )
        return self.session.scalars(stmt).first()

    def get_by_source_and_external_id(self, source_id: UUID, external_id: str) -> SourceItem | None:
        stmt = select(SourceItem).where(
            SourceItem.source_id == source_id,
            SourceItem.external_id == external_id,
        )
        return self.session.scalars(stmt).first()

    def get_by_source_and_canonical_url(self, source_id: UUID, canonical_url: str) -> SourceItem | None:
        stmt = select(SourceItem).where(
            SourceItem.source_id == source_id,
            SourceItem.canonical_url == canonical_url,
        )
        return self.session.scalars(stmt).first()

    def get_by_canonical_url(self, canonical_url: str) -> SourceItem | None:
        stmt = select(SourceItem).where(
            or_(SourceItem.canonical_url == canonical_url, SourceItem.url == canonical_url)
        )
        return self.session.scalars(stmt).first()

    def list_recent(self, *, source_id: UUID | None = None, limit: int = 50) -> list[SourceItem]:
        stmt = select(SourceItem).order_by(SourceItem.detected_at.desc()).limit(limit)
        if source_id is not None:
            stmt = stmt.where(SourceItem.source_id == source_id)
        return list(self.session.scalars(stmt))

    def list_pending(self, *, limit: int = 50) -> list[SourceItem]:
        stmt = (
            select(SourceItem)
            .where(SourceItem.processing_status == SourceItemStatus.PENDING)
            .order_by(SourceItem.detected_at.desc())
            .limit(limit)
        )
        return list(self.session.scalars(stmt))

    def list_retryable(self, *, limit: int = 50) -> list[SourceItem]:
        stmt = (
            select(SourceItem)
            .where(
                SourceItem.processing_status.in_(
                    (SourceItemStatus.PENDING, SourceItemStatus.FAILED)
                )
            )
            .order_by(SourceItem.detected_at.desc())
            .limit(limit)
        )
        return list(self.session.scalars(stmt))

    def count_since(self, since: datetime) -> int:
        stmt = select(SourceItem).where(SourceItem.detected_at >= since)
        return len(list(self.session.scalars(stmt)))

    def count_by_status(self) -> dict[str, int]:
        stmt = select(SourceItem.processing_status, func.count()).group_by(SourceItem.processing_status)
        return {status.value if hasattr(status, "value") else str(status): int(count) for status, count in self.session.execute(stmt)}


class EventRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, event: Event) -> Event:
        self.session.add(event)
        return event

    def get(self, event_id: UUID) -> Event | None:
        return self.session.get(Event, event_id)

    def get_by_public_id(self, public_id: UUID) -> Event | None:
        return self.session.scalars(select(Event).where(Event.public_id == public_id)).first()

    def get_with_details(self, event_id: UUID) -> Event | None:
        stmt = (
            select(Event)
            .options(
                selectinload(Event.event_sources)
                .selectinload(EventSource.source_item)
                .selectinload(SourceItem.source),
                selectinload(Event.event_entities),
                selectinload(Event.updates),
                selectinload(Event.claims).selectinload(Claim.evidence),
            )
            .where(Event.id == event_id)
        )
        return self.session.scalars(stmt).first()

    def list_recent(self, *, limit: int = 50) -> list[Event]:
        stmt = select(Event).order_by(Event.detected_at.desc()).limit(limit)
        return list(self.session.scalars(stmt))

    def count_since(self, since: datetime) -> int:
        stmt = select(Event).where(Event.detected_at >= since)
        return len(list(self.session.scalars(stmt)))

    def list_match_candidates(
        self,
        *,
        since: datetime,
        event_type: str | None = None,
        locality: str | None = None,
        limit: int = 40,
    ) -> list[Event]:
        stmt = select(Event).where(Event.detected_at >= since).order_by(Event.detected_at.desc()).limit(limit)
        if event_type:
            stmt = stmt.where(Event.event_type == event_type)
        if locality:
            stmt = stmt.where(Event.locality == locality)
        return list(self.session.scalars(stmt))

    def get_link(self, event_id: UUID, source_item_id: UUID) -> EventSource | None:
        stmt = select(EventSource).where(
            EventSource.event_id == event_id,
            EventSource.source_item_id == source_item_id,
        )
        return self.session.scalars(stmt).first()

    def get_link_for_item(self, source_item_id: UUID) -> EventSource | None:
        stmt = select(EventSource).where(EventSource.source_item_id == source_item_id)
        return self.session.scalars(stmt).first()

    def add_link(self, link: EventSource) -> EventSource:
        self.session.add(link)
        return link

    def canonical_urls_for_event(self, event_id: UUID) -> set[str]:
        stmt = (
            select(SourceItem.canonical_url, SourceItem.url)
            .join(EventSource, EventSource.source_item_id == SourceItem.id)
            .where(EventSource.event_id == event_id)
        )
        urls: set[str] = set()
        for canonical, url in self.session.execute(stmt):
            if canonical:
                urls.add(canonical)
            if url:
                urls.add(url)
        return urls

    def find_by_url(self, url: str) -> Event | None:
        stmt = (
            select(Event)
            .join(EventSource, EventSource.event_id == Event.id)
            .join(SourceItem, SourceItem.id == EventSource.source_item_id)
            .where(or_(SourceItem.canonical_url == url, SourceItem.url == url))
            .limit(1)
        )
        return self.session.scalars(stmt).first()

    def get_embedding(self, event_id: UUID) -> EventEmbedding | None:
        stmt = select(EventEmbedding).where(EventEmbedding.event_id == event_id)
        return self.session.scalars(stmt).first()

    def upsert_embedding(self, event_id: UUID, vector: list[float], model: str) -> EventEmbedding:
        existing = self.get_embedding(event_id)
        if existing is not None:
            existing.embedding = vector
            existing.model = model
            return existing
        row = EventEmbedding(event_id=event_id, embedding=vector, model=model)
        self.session.add(row)
        return row

    def add_entity_link(self, link: EventEntity) -> EventEntity:
        self.session.add(link)
        return link


class EntityRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_normalized(self, normalized_name: str, entity_type: EntityType) -> Entity | None:
        stmt = select(Entity).where(
            Entity.normalized_name == normalized_name,
            Entity.entity_type == entity_type,
        )
        return self.session.scalars(stmt).first()

    def list_for_event(self, event_id: UUID) -> list[Entity]:
        stmt = (
            select(Entity)
            .join(EventEntity, EventEntity.entity_id == Entity.id)
            .where(EventEntity.event_id == event_id)
        )
        return list(self.session.scalars(stmt))

    def add(self, entity: Entity) -> Entity:
        self.session.add(entity)
        return entity


class PipelineRunRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, run: PipelineRun) -> PipelineRun:
        self.session.add(run)
        return run

    def list_for_event(self, event_id: UUID, *, limit: int = 20) -> list[PipelineRun]:
        stmt = (
            select(PipelineRun)
            .where(PipelineRun.event_id == event_id)
            .order_by(PipelineRun.started_at.desc())
            .limit(limit)
        )
        return list(self.session.scalars(stmt))

    def list_for_item(self, source_item_id: UUID, *, limit: int = 20) -> list[PipelineRun]:
        stmt = (
            select(PipelineRun)
            .where(PipelineRun.source_item_id == source_item_id)
            .order_by(PipelineRun.started_at.desc())
            .limit(limit)
        )
        return list(self.session.scalars(stmt))

    def count_failed_since(self, since: datetime) -> int:
        stmt = select(PipelineRun).where(
            PipelineRun.started_at >= since,
            PipelineRun.status == PipelineStatus.FAILED,
        )
        return len(list(self.session.scalars(stmt)))

    def latest_failed_error(self) -> str | None:
        latest = self.session.scalars(
            select(PipelineRun).order_by(PipelineRun.started_at.desc()).limit(1)
        ).first()
        if latest is None or latest.status != PipelineStatus.FAILED:
            return None
        return latest.error_message

    def get_running(self, event_id: UUID, stage: str) -> PipelineRun | None:
        stmt = select(PipelineRun).where(
            PipelineRun.event_id == event_id,
            PipelineRun.stage == stage,
            PipelineRun.status == PipelineStatus.RUNNING,
        )
        return self.session.scalars(stmt).first()

    def latest_success(self, event_id: UUID, stage: str) -> PipelineRun | None:
        stmt = (
            select(PipelineRun)
            .where(
                PipelineRun.event_id == event_id,
                PipelineRun.stage == stage,
                PipelineRun.status == PipelineStatus.SUCCESS,
            )
            .order_by(PipelineRun.started_at.desc())
            .limit(1)
        )
        return self.session.scalars(stmt).first()

    def count_running_by_stage(self) -> dict[str, int]:
        stmt = (
            select(PipelineRun.stage, func.count())
            .where(PipelineRun.status == PipelineStatus.RUNNING)
            .group_by(PipelineRun.stage)
        )
        return {stage: int(count) for stage, count in self.session.execute(stmt)}

    def count_by_stage_status_since(self, since: datetime) -> list[dict]:
        stmt = (
            select(PipelineRun.stage, PipelineRun.status, func.count())
            .where(PipelineRun.started_at >= since)
            .group_by(PipelineRun.stage, PipelineRun.status)
        )
        rows = []
        for stage, status, count in self.session.execute(stmt):
            rows.append(
                {
                    "stage": stage,
                    "status": status.value if hasattr(status, "value") else str(status),
                    "count": int(count),
                }
            )
        return rows

    def latest_for_events(self, event_ids: list[UUID]) -> dict[UUID, PipelineRun]:
        if not event_ids:
            return {}
        # Postgres DISTINCT ON: latest started_at per event_id
        stmt = (
            select(PipelineRun)
            .where(PipelineRun.event_id.in_(event_ids))
            .order_by(PipelineRun.event_id, PipelineRun.started_at.desc())
            .distinct(PipelineRun.event_id)
        )
        return {run.event_id: run for run in self.session.scalars(stmt).all() if run.event_id}


class LlmUsageRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, row: LlmUsage) -> LlmUsage:
        self.session.add(row)
        return row

    def totals_since(self, since: datetime) -> dict:
        stmt = select(
            func.coalesce(func.sum(LlmUsage.prompt_tokens), 0),
            func.coalesce(func.sum(LlmUsage.completion_tokens), 0),
            func.coalesce(func.sum(LlmUsage.total_tokens), 0),
            func.count(),
        ).where(LlmUsage.created_at >= since)
        prompt, completion, total, calls = self.session.execute(stmt).one()
        return {
            "prompt_tokens": int(prompt),
            "completion_tokens": int(completion),
            "total_tokens": int(total),
            "calls": int(calls),
        }

    def totals_by_role_since(self, since: datetime) -> list[dict]:
        stmt = (
            select(
                LlmUsage.model_role,
                func.coalesce(func.sum(LlmUsage.prompt_tokens), 0),
                func.coalesce(func.sum(LlmUsage.completion_tokens), 0),
                func.coalesce(func.sum(LlmUsage.total_tokens), 0),
                func.count(),
            )
            .where(LlmUsage.created_at >= since)
            .group_by(LlmUsage.model_role)
            .order_by(func.sum(LlmUsage.total_tokens).desc())
        )
        return [
            {
                "model_role": role or "unknown",
                "prompt_tokens": int(prompt),
                "completion_tokens": int(completion),
                "total_tokens": int(total),
                "calls": int(calls),
            }
            for role, prompt, completion, total, calls in self.session.execute(stmt)
        ]

    def totals_for_event(self, event_id: UUID) -> dict:
        stmt = select(
            func.coalesce(func.sum(LlmUsage.prompt_tokens), 0),
            func.coalesce(func.sum(LlmUsage.completion_tokens), 0),
            func.coalesce(func.sum(LlmUsage.total_tokens), 0),
            func.count(),
        ).where(LlmUsage.event_id == event_id)
        prompt, completion, total, calls = self.session.execute(stmt).one()
        return {
            "prompt_tokens": int(prompt),
            "completion_tokens": int(completion),
            "total_tokens": int(total),
            "calls": int(calls),
        }

    def totals_by_role_for_event(self, event_id: UUID) -> list[dict]:
        stmt = (
            select(
                LlmUsage.model_role,
                LlmUsage.stage,
                func.coalesce(func.sum(LlmUsage.prompt_tokens), 0),
                func.coalesce(func.sum(LlmUsage.completion_tokens), 0),
                func.coalesce(func.sum(LlmUsage.total_tokens), 0),
                func.count(),
            )
            .where(LlmUsage.event_id == event_id)
            .group_by(LlmUsage.model_role, LlmUsage.stage)
            .order_by(func.sum(LlmUsage.total_tokens).desc())
        )
        return [
            {
                "model_role": role or "unknown",
                "stage": stage or "unknown",
                "prompt_tokens": int(prompt),
                "completion_tokens": int(completion),
                "total_tokens": int(total),
                "calls": int(calls),
            }
            for role, stage, prompt, completion, total, calls in self.session.execute(stmt)
        ]

    def totals_for_events(self, event_ids: list[UUID]) -> dict[UUID, int]:
        if not event_ids:
            return {}
        stmt = (
            select(LlmUsage.event_id, func.coalesce(func.sum(LlmUsage.total_tokens), 0))
            .where(LlmUsage.event_id.in_(event_ids))
            .group_by(LlmUsage.event_id)
        )
        return {event_id: int(total) for event_id, total in self.session.execute(stmt) if event_id}


class ArticleRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, article: Article) -> Article:
        self.session.add(article)
        return article

    def get(self, article_id: UUID) -> Article | None:
        return self.session.get(Article, article_id)

    def get_by_event_id(self, event_id: UUID) -> Article | None:
        return self.session.scalars(select(Article).where(Article.event_id == event_id)).first()

    def get_by_slug(self, slug: str) -> Article | None:
        return self.session.scalars(select(Article).where(Article.slug == slug)).first()

    def get_version(self, article_id: UUID, version_number: int) -> ArticleVersion | None:
        stmt = select(ArticleVersion).where(
            ArticleVersion.article_id == article_id,
            ArticleVersion.version_number == version_number,
        )
        return self.session.scalars(stmt).first()
