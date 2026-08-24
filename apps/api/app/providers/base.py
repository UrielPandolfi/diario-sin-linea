from datetime import datetime
from typing import Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class ProviderNotConfiguredError(RuntimeError):
    pass


class SearchQuery(BaseModel):
    text: str
    count: int
    freshness: str | None = None
    since: datetime | None = None
    until: datetime | None = None


class SearchHit(BaseModel):
    title: str
    url: str
    snippet: str | None = None


class SearchProvider(Protocol):
    def search(self, query: SearchQuery) -> list[SearchHit]: ...


class StructuredLLMProvider(Protocol):
    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema: type[T],
    ) -> T: ...


class EmbeddingProvider(Protocol):
    model: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...
