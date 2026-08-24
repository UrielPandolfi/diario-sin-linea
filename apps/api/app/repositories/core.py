from datetime import datetime
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Article,
    Claim,
    Entity,
    Event,
    EventEmbedding,
    EventEntity,
    EventSource,
    PipelineRun,
    Source,
    SourceItem,
)
from app.domain.enums import EntityType, PipelineStatus


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

    def count_since(self, since: datetime) -> int:
        stmt = select(SourceItem).where(SourceItem.detected_at >= since)
        return len(list(self.session.scalars(stmt)))


class EventRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, event: Event) -> Event:
        self.session.add(event)
        return event

    def get(self, event_id: UUID) -> Event | None:
        return self.session.get(Event, event_id)

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

    def get_running(self, event_id: UUID, stage: str) -> PipelineRun | None:
        stmt = select(PipelineRun).where(
            PipelineRun.event_id == event_id,
            PipelineRun.stage == stage,
            PipelineRun.status == PipelineStatus.RUNNING,
        )
        return self.session.scalars(stmt).first()


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
