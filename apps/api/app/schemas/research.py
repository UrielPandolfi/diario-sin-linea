from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class ResearchRelevance(StrEnum):
    SAME_EVENT = "SAME_EVENT"
    RELATED_CONTEXT = "RELATED_CONTEXT"
    DIFFERENT_EVENT = "DIFFERENT_EVENT"
    IRRELEVANT = "IRRELEVANT"


class ResearchQueries(BaseModel):
    queries: list[str] = Field(default_factory=list)


class RelevanceHit(BaseModel):
    url: str
    classification: ResearchRelevance = ResearchRelevance.IRRELEVANT
    confidence: float | None = None

    @field_validator("classification", mode="before")
    @classmethod
    def _normalize_classification(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().upper().replace("-", "_").replace(" ", "_")
        return value

    @model_validator(mode="before")
    @classmethod
    def _accept_legacy_relevant(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        if "classification" not in data and "relevant" in data:
            data = dict(data)
            data["classification"] = (
                ResearchRelevance.SAME_EVENT
                if data.get("relevant")
                else ResearchRelevance.IRRELEVANT
            )
        return data


class RelevanceBatch(BaseModel):
    hits: list[RelevanceHit] = Field(default_factory=list)
