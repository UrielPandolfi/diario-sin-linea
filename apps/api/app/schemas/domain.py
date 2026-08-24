from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.domain.enums import (
    ArticleStatus,
    EventSourceRelation,
    EventStatus,
    IngestionMethod,
    LocationPrecision,
    SourceItemStatus,
)


class SourceCreate(BaseModel):
    name: str
    domain: str | None = None
    homepage_url: str | None = None
    source_type: str | None = None
    preferred_ingestion_method: IngestionMethod = IngestionMethod.UNKNOWN
    feed_url: str | None = None
    endpoint_url: str | None = None
    is_monitored: bool = False
    is_enabled: bool = True


class SourceUpdate(BaseModel):
    name: str | None = None
    domain: str | None = None
    homepage_url: str | None = None
    source_type: str | None = None
    preferred_ingestion_method: IngestionMethod | None = None
    feed_url: str | None = None
    endpoint_url: str | None = None
    is_monitored: bool | None = None
    is_enabled: bool | None = None


class SourceItemCreate(BaseModel):
    source_id: UUID
    url: str
    content_hash: str
    external_id: str | None = None
    canonical_url: str | None = None
    title: str | None = None
    raw_text: str | None = None
    clean_text: str | None = None
    excerpt: str | None = None
    author: str | None = None
    published_at: datetime | None = None
    processing_status: SourceItemStatus = SourceItemStatus.PENDING


class EventCreate(BaseModel):
    title_internal: str
    event_type: str = "unknown"
    source_item_id: UUID | None = None
    started_at: datetime | None = None
    country_code: str | None = "AR"
    province: str | None = None
    locality: str | None = None
    neighborhood: str | None = None
    address_text: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    location_precision: LocationPrecision | None = None
    relevance_score: int = Field(default=0, ge=0, le=100)
    short_summary: str | None = None
    slug: str | None = None
    status: EventStatus = EventStatus.DETECTED


class EventSourceAttach(BaseModel):
    event_id: UUID
    source_item_id: UUID
    relation_type: EventSourceRelation = EventSourceRelation.ADDITIONAL
    is_primary: bool = False


class ArticleCreate(BaseModel):
    event_id: UUID
    headline: str
    summary: str
    body: str
    slug: str | None = None
    status: ArticleStatus = ArticleStatus.DRAFT
    hero_image_url: str | None = None


class ArticleContentUpdate(BaseModel):
    headline: str
    summary: str
    body: str
    change_reason: str
    hero_image_url: str | None = None
