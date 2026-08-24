from pydantic import BaseModel, Field


class ResearchQueries(BaseModel):
    queries: list[str] = Field(default_factory=list)


class RelevanceHit(BaseModel):
    url: str
    relevant: bool = False


class RelevanceBatch(BaseModel):
    hits: list[RelevanceHit] = Field(default_factory=list)
