from typing import TypeVar

from openai import BadRequestError, OpenAI
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


def _model_allows_temperature_zero(model: str) -> bool:
    """Algunos modelos OpenAI (gpt-5 base, o-series) solo admiten temperature default (1)."""
    name = (model or "").casefold()
    if any(token in name for token in ("o1", "o3", "o4-mini", "o4_mini")):
        return False
    # gpt-5 / gpt-5.6 "reasoning-style" aliases; chat-latest variants varían, mejor omitir 0.
    if name.startswith("gpt-5") and "chat" not in name and "4o" not in name:
        return False
    return True


class OpenAIStructuredProvider:
    def __init__(self, *, api_key: str, model: str, base_url: str | None = None) -> None:
        self.model = model
        kwargs: dict = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self.client = OpenAI(**kwargs)

    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema: type[T],
    ) -> T:
        last_error: Exception | None = None
        messages = [
            {
                "role": "system",
                "content": (
                    f"{system_prompt}\n\n"
                    "Respondé únicamente JSON válido que respete el esquema."
                ),
            },
            {"role": "user", "content": user_prompt},
        ]
        for _ in range(2):
            try:
                create_kwargs: dict = {
                    "model": self.model,
                    "messages": messages,
                    "response_format": {"type": "json_object"},
                }
                if _model_allows_temperature_zero(self.model):
                    create_kwargs["temperature"] = 0
                try:
                    response = self.client.chat.completions.create(**create_kwargs)
                except BadRequestError as exc:
                    # Retry sin temperature si el modelo la rechaza (p.ej. gpt-5 / o-series).
                    if "temperature" not in str(exc).casefold():
                        raise
                    create_kwargs.pop("temperature", None)
                    response = self.client.chat.completions.create(**create_kwargs)
                content = response.choices[0].message.content or "{}"
                return schema.model_validate_json(content)
            except (ValidationError, ValueError, KeyError) as exc:
                last_error = exc
        raise last_error or RuntimeError("structured output failed")


class OpenAIEmbeddingProvider:
    def __init__(self, *, api_key: str, model: str) -> None:
        self.model = model
        self.client = OpenAI(api_key=api_key)

    def embed(self, texts: list[str]) -> list[list[float]]:
        response = self.client.embeddings.create(model=self.model, input=texts)
        return [item.embedding for item in response.data]
