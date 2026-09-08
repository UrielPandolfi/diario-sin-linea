from __future__ import annotations

import json
import time
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.providers.structured_format import format_schema_retry_feedback

T = TypeVar("T", bound=BaseModel)


def parse_json_payload(text: str) -> dict[str, Any]:
    stripped = (text or "").strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[-1]
        fence = stripped.rfind("```")
        if fence != -1:
            stripped = stripped[:fence].strip()
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end == -1:
            raise
        payload = json.loads(stripped[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("json payload must be an object")
    return payload


def parse_structured(text: str, schema: type[T]) -> T:
    return schema.model_validate(parse_json_payload(text))


class AnthropicJsonProvider:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        max_output_tokens: int = 4096,
        client: Any | None = None,
    ) -> None:
        self.model = model
        self.max_output_tokens = max_output_tokens
        if client is not None:
            self.client = client
        else:
            from anthropic import Anthropic

            self.client = Anthropic(api_key=api_key)

    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema: type[T],
    ) -> T:
        last_error: Exception | None = None
        user_content = user_prompt
        for _ in range(2):
            try:
                # No pasar temperature: algunos clientes/SDK de Messages lo rechazan
                # (TypeError: unexpected keyword argument 'temperature').
                started = time.perf_counter()
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=self.max_output_tokens,
                    system=(
                        f"{system_prompt}\n\n"
                        "Respondé únicamente JSON válido que respete el esquema."
                    ),
                    messages=[{"role": "user", "content": user_content}],
                )
                from app.services.usage_recorder import extract_anthropic_usage_details, record_llm_usage

                duration_ms = int((time.perf_counter() - started) * 1000)
                details = extract_anthropic_usage_details(response)
                record_llm_usage(
                    provider="anthropic",
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
                content = "".join(
                    getattr(block, "text", "") or ""
                    for block in (response.content or [])
                )
                return parse_structured(content, schema)
            except (json.JSONDecodeError, ValidationError, ValueError, TypeError, KeyError) as exc:
                last_error = exc
                user_content = f"{user_prompt}\n\n{format_schema_retry_feedback(exc)}"
        raise last_error or RuntimeError("structured output failed")
