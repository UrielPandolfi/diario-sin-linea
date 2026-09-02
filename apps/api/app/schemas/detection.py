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


class EditorialTopic(StrEnum):
    NATIONAL_POLITICS = "NATIONAL_POLITICS"
    PROVINCIAL_POLITICS = "PROVINCIAL_POLITICS"
    GOVERNMENT = "GOVERNMENT"
    LEGISLATION = "LEGISLATION"
    ELECTIONS = "ELECTIONS"
    PUBLIC_ECONOMY = "PUBLIC_ECONOMY"
    PUBLIC_SECURITY = "PUBLIC_SECURITY"
    PUBLIC_EDUCATION = "PUBLIC_EDUCATION"
    PUBLIC_HEALTH = "PUBLIC_HEALTH"
    JUSTICE = "JUSTICE"
    CORRUPTION = "CORRUPTION"
    INTERNATIONAL_AR = "INTERNATIONAL_AR"
    OTHER_PUBLIC_AFFAIRS = "OTHER_PUBLIC_AFFAIRS"
    CRIME = "CRIME"
    ACCIDENT = "ACCIDENT"
    SPORTS = "SPORTS"
    ENTERTAINMENT = "ENTERTAINMENT"
    OTHER = "OTHER"


class RelevanceLevel(StrEnum):
    NONE = "NONE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ExtractedEntity(BaseModel):
    name: str
    entity_type: EntityType = EntityType.OTHER
    role: str = "mencionado"


def _normalize_enum_token(value: object) -> object:
    if isinstance(value, str):
        return value.strip().upper().replace("-", "_").replace(" ", "_")
    return value


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
    editorial_topic: EditorialTopic = EditorialTopic.OTHER
    is_public_affairs: bool = False
    political_relevance: RelevanceLevel = RelevanceLevel.NONE
    public_interest_relevance: RelevanceLevel = RelevanceLevel.NONE
    has_contestable_public_claims: bool = False
    argentina_relevance: bool = False
    gate_reason: str | None = None
    location_confidence: float = Field(default=0.5, ge=0.0, le=1.0)

    @field_validator("editorial_scope", "editorial_topic", "political_relevance", "public_interest_relevance", mode="before")
    @classmethod
    def _normalize_editorial_enums(cls, value: object) -> object:
        return _normalize_enum_token(value)


class DedupDecision(BaseModel):
    decision: Literal["EXISTING_EVENT", "NEW_EVENT"]
    event_id: UUID | None = None
    confidence: float = 0.0
    reason: str = ""
