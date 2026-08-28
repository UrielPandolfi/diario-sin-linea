from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.domain.enums import EntityType


class EditorialScope(StrEnum):
    GENERAL_NEWS = "GENERAL_NEWS"
    SPORTS_ONLY = "SPORTS_ONLY"
    SPORTS_PUBLIC_IMPACT = "SPORTS_PUBLIC_IMPACT"
    IRRELEVANT = "IRRELEVANT"


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
    editorial_scope: EditorialScope = EditorialScope.GENERAL_NEWS
    editorial_reason: str | None = None
    location_confidence: float = Field(default=0.5, ge=0.0, le=1.0)

    @field_validator("editorial_scope", mode="before")
    @classmethod
    def _normalize_editorial_scope(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().upper().replace("-", "_").replace(" ", "_")
        return value


class DedupDecision(BaseModel):
    decision: Literal["EXISTING_EVENT", "NEW_EVENT"]
    event_id: UUID | None = None
    confidence: float = 0.0
    reason: str = ""
