import hashlib
from typing import Any, TypeVar

from pydantic import BaseModel

from app.providers.base import ProviderNotConfiguredError, SearchHit, SearchQuery

T = TypeVar("T", bound=BaseModel)


class FakeStructuredLLM:
    def __init__(self, responses: dict[str, BaseModel | Exception | list] | None = None) -> None:
        self.responses = responses or {}
        self.calls: list[str] = []
        self.user_prompts: list[str] = []

    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema: type[T],
    ) -> T:
        self.calls.append(schema.__name__)
        self.user_prompts.append(user_prompt)
        payload = self.responses.get(schema.__name__)
        if payload is None:
            raise ProviderNotConfiguredError(f"No hay fake para {schema.__name__}")
        if isinstance(payload, list):
            index = self.calls.count(schema.__name__) - 1
            payload = payload[index]
        if isinstance(payload, Exception):
            raise payload
        return payload  # type: ignore[return-value]


class FakeEmbeddingProvider:
    def __init__(self, *, model: str = "fake-embed", dimension: int = 1024) -> None:
        self.model = model
        self.dimension = dimension
        self.mode = "low"
        self._seen: dict[str, int] = {}

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        slots = max(1, self.dimension - 16)
        for text in texts:
            vector = [0.0] * self.dimension
            mode = self.mode
            lowered = text.lower()
            if "duplicate-high" in lowered or mode == "high":
                vector[0] = 1.0
            elif "duplicate-mid" in lowered or mode == "mid":
                vector[0] = 0.8
                vector[1] = 0.6
            else:
                if text not in self._seen:
                    self._seen[text] = len(self._seen)
                vector[16 + (self._seen[text] % slots)] = 1.0
            vectors.append(vector)
        return vectors


class FakeSearchProvider:
    def __init__(self, hits: list[SearchHit] | dict[str, list[SearchHit]] | None = None) -> None:
        self.hits = hits or []
        self.queries: list[SearchQuery] = []

    def search(self, query: SearchQuery) -> list[SearchHit]:
        self.queries.append(query)
        if isinstance(self.hits, dict):
            return list(self.hits.get(query.text, []))
        return list(self.hits)


class RecordingFetcher:
    def __init__(
        self,
        pages: dict[str, str] | None = None,
        errors: dict[str, Exception | list[Exception]] | None = None,
    ) -> None:
        self.pages = pages or {}
        self.errors = {
            url: list(exc) if isinstance(exc, list) else [exc]
            for url, exc in (errors or {}).items()
        }
        self.fetched: list[str] = []

    def fetch(self, url: str, *, timeout: float = 20.0):
        from app.services.fetching import FetchResult

        self.fetched.append(url)
        pending = self.errors.get(url)
        if pending:
            raise pending.pop(0)
        body = self.pages.get(url, f"<article><p>Texto de {url}</p></article>")
        return FetchResult(url=url, body=body, content_type="text/html")
