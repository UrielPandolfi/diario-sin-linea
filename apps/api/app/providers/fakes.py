import hashlib
from typing import Any, TypeVar

from pydantic import BaseModel

from app.providers.base import ProviderNotConfiguredError

T = TypeVar("T", bound=BaseModel)


class FakeStructuredLLM:
    def __init__(self, responses: dict[str, BaseModel | Exception | list] | None = None) -> None:
        self.responses = responses or {}
        self.calls: list[str] = []

    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema: type[T],
    ) -> T:
        self.calls.append(schema.__name__)
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
