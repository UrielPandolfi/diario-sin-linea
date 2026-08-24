from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.domain.enums import EntityType


class ExtractedEntity(BaseModel):
    name: str
    entity_type: EntityType = EntityType.OTHER
    role: str = "mencionado"


class EventCandidate(BaseModel):
    event_type: str = "unknown"
    what_happened: str
    occurred_at: datetime | None = None
    country_code: str | None = "AR"
    province: str | None = None
    locality: str | None = None
    neighborhood: str | None = None
    address_text: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    entities: list[ExtractedEntity] = Field(default_factory=list)
    short_summary: str


class DedupDecision(BaseModel):
    decision: Literal["EXISTING_EVENT", "NEW_EVENT"]
    event_id: UUID | None = None
    confidence: float = 0.0
    reason: str = ""
