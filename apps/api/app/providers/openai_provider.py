import time
from typing import Any, TypeVar

from openai import BadRequestError, RateLimitError, OpenAI
from pydantic import BaseModel, ValidationError

from app.providers.rate_limit import with_rate_limit_retry
from app.providers.structured_format import format_schema_retry_feedback, openai_json_schema_format

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


def _reasoning_effort_for_model(model: str) -> str | None:
    """Effort mínimo solo para nano. No inferir por prefijo gpt-5 (Luna usa none/low/…)."""
    name = (model or "").casefold()
    if "nano" in name:
        return "minimal"
    return None


class OpenAIStructuredProvider:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str | None = None,
        provider_name: str = "openai",
        client: Any | None = None,
        reasoning_effort: str | None = None,
    ) -> None:
        self.model = model
        self.provider_name = provider_name
        self.reasoning_effort = (reasoning_effort or "").strip() or None
        if client is not None:
            self.client = client
        else:
            kwargs: dict = {"api_key": api_key, "max_retries": 0}
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
                    "response_format": openai_json_schema_format(schema),
                }
                if _model_allows_temperature_zero(self.model):
                    create_kwargs["temperature"] = 0
                effort = self.reasoning_effort or _reasoning_effort_for_model(self.model)
                if effort:
                    create_kwargs["reasoning_effort"] = effort
                response, duration_ms = self._create_completion(create_kwargs)
                from app.services.usage_recorder import extract_openai_usage_details, record_llm_usage

                details = extract_openai_usage_details(response)
                record_llm_usage(
                    provider=self.provider_name,
                    model=self.model,
                    prompt_tokens=details.prompt_tokens,
                    completion_tokens=details.completion_tokens,
                    total_tokens=details.total_tokens,
                    cache_read_tokens=details.cache_read_tokens,
                    cache_write_tokens=details.cache_write_tokens,
                    model_reported=details.model_reported,
                    usage_reported=details.usage_reported,
                    duration_ms=duration_ms,
                )
                content = response.choices[0].message.content or "{}"
                return schema.model_validate_json(content)
            except (ValidationError, ValueError, KeyError) as exc:
                last_error = exc
                messages = [
                    messages[0],
                    {"role": "user", "content": user_prompt},
                    {"role": "user", "content": format_schema_retry_feedback(exc)},
                ]
        raise last_error or RuntimeError("structured output failed")

    def _create_completion(self, create_kwargs: dict) -> tuple[Any, int]:
        return with_rate_limit_retry(lambda: self._create_completion_once(create_kwargs))

    def _create_completion_once(self, create_kwargs: dict) -> tuple[Any, int]:
        started = time.perf_counter()
        try:
            response = self.client.chat.completions.create(**create_kwargs)
        except RateLimitError:
            failed_ms = int((time.perf_counter() - started) * 1000)
            self._record_failed_attempt(duration_ms=failed_ms)
            raise
        except BadRequestError as exc:
            failed_ms = int((time.perf_counter() - started) * 1000)
            self._record_failed_attempt(duration_ms=failed_ms)
            message = str(exc).casefold()
            stripped = False
            for key in ("reasoning_effort", "temperature"):
                if key in create_kwargs and key in message:
                    create_kwargs.pop(key, None)
                    stripped = True
            response_format = create_kwargs.get("response_format") or {}
            if response_format.get("type") == "json_schema" and (
                "json_schema" in message
                or "response_format" in message
                or "strict" in message
                or "schema" in message
            ):
                create_kwargs["response_format"] = {"type": "json_object"}
                stripped = True
            if not stripped:
                raise
            started = time.perf_counter()
            try:
                response = self.client.chat.completions.create(**create_kwargs)
            except RateLimitError:
                failed_ms = int((time.perf_counter() - started) * 1000)
                self._record_failed_attempt(duration_ms=failed_ms)
                raise
        duration_ms = int((time.perf_counter() - started) * 1000)
        return response, duration_ms

    def _record_failed_attempt(self, *, duration_ms: int) -> None:
        from app.services.usage_recorder import record_llm_usage

        record_llm_usage(
            provider=self.provider_name,
            model=self.model,
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            duration_ms=duration_ms,
            usage_reported=False,
            failed=True,
        )


class OpenAIEmbeddingProvider:
    def __init__(self, *, api_key: str, model: str, provider_name: str = "openai"):
        self.model = model
        self.provider_name = provider_name
        self.client = OpenAI(api_key=api_key)

    def embed(self, texts: list[str]) -> list[list[float]]:
        started = time.perf_counter()
        response = self.client.embeddings.create(model=self.model, input=texts)
        duration_ms = int((time.perf_counter() - started) * 1000)
        from app.services.usage_recorder import extract_openai_usage_details, record_llm_usage

        details = extract_openai_usage_details(response)
        record_llm_usage(
            provider=self.provider_name,
            model=self.model,
            prompt_tokens=details.prompt_tokens,
            completion_tokens=details.completion_tokens,
            total_tokens=details.total_tokens,
            cache_read_tokens=details.cache_read_tokens,
            cache_write_tokens=details.cache_write_tokens,
            model_reported=details.model_reported,
            usage_reported=details.usage_reported,
            duration_ms=duration_ms,
        )
        return [item.embedding for item in response.data]
