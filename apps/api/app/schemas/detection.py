from datetime import date, datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.core.text import is_placeholder_text
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
    occurred_at: datetime | None = Field(
        default=None,
        description="Instante del suceso solo con hora explícita y fecha identificable en la fuente. "
        "Fecha sin hora u hora aproximada: null. No usar la hora de publicación ni completar con medianoche.",
    )
    country_code: str | None = Field(default="AR", description="País del suceso, código ISO 3166-1 alpha-2.")
    province: str | None = Field(
        default=None, description="Jurisdicción de primer nivel: provincia o ciudad autónoma. "
        "CABA: Ciudad Autónoma de Buenos Aires; distinta de la provincia de Buenos Aires.",
    )
    locality: str | None = Field(
        default=None, description="Ciudad o localidad del suceso, no provincia ni barrio. "
        "Para CABA: Ciudad Autónoma de Buenos Aires.",
    )
    neighborhood: str | None = Field(default=None, description="Barrio dentro de la localidad, solo si está identificado.")
    address_text: str | None = Field(default=None, description="Dirección o intersección explícita del suceso.")
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

    @field_validator(
        "country_code", "province", "locality", "neighborhood", "address_text",
        "editorial_reason", "gate_reason", "occurred_at", "latitude", "longitude",
        mode="before",
    )
    @classmethod
    def _normalize_optional_values(cls, value: object) -> object:
        if isinstance(value, str):
            return None if is_placeholder_text(value) else value.strip()
        return value

    @field_validator("occurred_at", mode="before")
    @classmethod
    def _do_not_promote_date_to_midnight(cls, value: object) -> object:
        # A date alone is not an instant. Keep the existing datetime schema;
        # the source/what_happened can retain the date without inventing an hour.
        if isinstance(value, date) and not isinstance(value, datetime):
            return None
        if isinstance(value, str):
            try:
                date.fromisoformat(value.strip())
            except ValueError:
                pass
            else:
                return None
        return value

    @field_validator("editorial_scope", "editorial_topic", "political_relevance", "public_interest_relevance", mode="before")
    @classmethod
    def _normalize_editorial_enums(cls, value: object) -> object:
        return _normalize_enum_token(value)


class DedupDecision(BaseModel):
    decision: Literal["EXISTING_EVENT", "NEW_EVENT"]
    event_id: UUID | None = None
    confidence: float = 0.0
    reason: str = ""


class AmbiguousDedupDecision(BaseModel):
    decision: Literal["SAME_EVENT", "DIFFERENT_EVENT", "UNSURE"]
    confidence: float = 0.0
    reason: str = ""

    @field_validator("decision", mode="before")
    @classmethod
    def _normalize_decision(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        token = value.strip().upper().replace("-", "_").replace(" ", "_")
        aliases = {
            "EXISTING_EVENT": "SAME_EVENT",
            "SAME": "SAME_EVENT",
            "NEW_EVENT": "DIFFERENT_EVENT",
            "DIFFERENT": "DIFFERENT_EVENT",
            "UNKNOWN": "UNSURE",
            "UNCERTAIN": "UNSURE",
        }
        return aliases.get(token, token)
