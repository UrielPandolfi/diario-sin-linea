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
    """chat.completions rechaza reasoning_effort en gpt-5-nano (HTTP 400). No inferirlo."""
    _ = (model or "").strip()
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
        thinking: str | None = None,
    ) -> None:
        self.model = model
        self.provider_name = provider_name
        self.reasoning_effort = (reasoning_effort or "").strip() or None
        self.thinking = (thinking or "").strip() or None
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
                }
                if self.provider_name.lower() == "deepseek":
                    create_kwargs["response_format"] = {"type": "json_object"}
                else:
                    create_kwargs["response_format"] = openai_json_schema_format(schema)
                if _model_allows_temperature_zero(self.model):
                    create_kwargs["temperature"] = 0
                effort = self.reasoning_effort or _reasoning_effort_for_model(self.model)
                if effort:
                    create_kwargs["reasoning_effort"] = effort
                if self.provider_name.lower() == "deepseek" and self.thinking == "disabled":
                    create_kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
                response, duration_ms = self._create_completion(create_kwargs)
                from app.services.usage_recorder import extract_openai_usage_details, record_llm_usage

                details = extract_openai_usage_details(response)
                message = response.choices[0].message
                record_llm_usage(
                    provider=self.provider_name,
                    model=self.model,
                    prompt_tokens=details.prompt_tokens,
                    completion_tokens=details.completion_tokens,
                    total_tokens=details.total_tokens,
                    cache_read_tokens=details.cache_read_tokens,
                    cache_write_tokens=details.cache_write_tokens,
                    reasoning_tokens=details.reasoning_tokens,
                    model_reported=details.model_reported,
                    usage_reported=details.usage_reported,
                    duration_ms=duration_ms,
                    request_options=_request_options(create_kwargs, message),
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
        from app.core.config import get_settings
        from app.services.call_budget import CallBudgetExceeded, active_budget
        from app.services.cost_service import actual_usage_usd, reserve_estimate_usd

        budget = active_budget()
        hold = None
        if budget is not None:
            attempts = 1 + max(0, int(get_settings().job_max_retries))
            estimate = reserve_estimate_usd(
                provider=self.provider_name,
                model=self.model,
                prompt_chars=_prompt_chars(create_kwargs),
                max_output_tokens=4096,
            ) * attempts
            try:
                hold = budget.reserve(estimate)
            except CallBudgetExceeded:
                self._record_failed_attempt(
                    duration_ms=0,
                    request_options={"budget_blocked": True, "thinking": self.thinking},
                )
                raise
        try:
            response, duration_ms = with_rate_limit_retry(lambda: self._create_completion_once(create_kwargs))
        except Exception:
            if budget is not None and hold is not None:
                budget.release(hold)
            raise
        if budget is not None and hold is not None:
            actual = actual_usage_usd(self.provider_name, self.model, response)
            budget.settle(hold, actual if actual is not None else hold)
        return response, duration_ms

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

    def _record_failed_attempt(self, *, duration_ms: int, request_options: dict | None = None) -> None:
        from app.services.usage_recorder import record_llm_usage

        options = {"thinking": self.thinking}
        if request_options:
            options.update(request_options)
        record_llm_usage(
            provider=self.provider_name,
            model=self.model,
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            duration_ms=duration_ms,
            usage_reported=False,
            failed=True,
            request_options=options,
        )


def _prompt_chars(create_kwargs: dict) -> int:
    total = 0
    for message in create_kwargs.get("messages") or []:
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, str):
            total += len(content)
    return total


def _request_options(create_kwargs: dict, message: Any) -> dict:
    extra = create_kwargs.get("extra_body") if isinstance(create_kwargs.get("extra_body"), dict) else {}
    thinking = extra.get("thinking") if isinstance(extra, dict) else None
    reasoning_content = getattr(message, "reasoning_content", None)
    return {
        "thinking": thinking,
        "reasoning_effort": create_kwargs.get("reasoning_effort"),
        "reasoning_content_present": reasoning_content is not None,
    }


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
