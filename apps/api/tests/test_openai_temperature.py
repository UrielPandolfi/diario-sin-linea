from types import SimpleNamespace

from pydantic import BaseModel

from app.providers.openai_provider import (
    OpenAIStructuredProvider,
    _model_allows_temperature_zero,
    _reasoning_effort_for_model,
)


def test_temperature_zero_allowed_for_standard_models() -> None:
    assert _model_allows_temperature_zero("gpt-4o-mini") is True
    assert _model_allows_temperature_zero("gpt-4o") is True
    assert _model_allows_temperature_zero("gpt-4.1-mini") is True


def test_temperature_zero_blocked_for_reasoning_style_models() -> None:
    assert _model_allows_temperature_zero("gpt-5.6-luna") is False
    assert _model_allows_temperature_zero("gpt-5") is False
    assert _model_allows_temperature_zero("o3-mini") is False
    assert _model_allows_temperature_zero("o1") is False


def test_reasoning_effort_minimal_only_for_nano() -> None:
    assert _reasoning_effort_for_model("gpt-5-nano") == "minimal"
    assert _reasoning_effort_for_model("gpt-5") is None
    assert _reasoning_effort_for_model("gpt-5.6-luna") is None
    assert _reasoning_effort_for_model("gpt-4o-mini") is None
    assert _reasoning_effort_for_model("deepseek-v4-flash") is None


class _Tiny(BaseModel):
    x: int


def test_explicit_reasoning_effort_none_is_sent(monkeypatch) -> None:
    monkeypatch.setattr("app.services.usage_recorder.record_llm_usage", lambda **_k: None)
    captured: dict = {}

    class Completions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
                choices=[SimpleNamespace(message=SimpleNamespace(content='{"x": 1}'))],
            )

    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    provider = OpenAIStructuredProvider(
        api_key="k", model="gpt-5.6-luna", client=client, reasoning_effort="none"
    )
    result = provider.generate_structured(system_prompt="s", user_prompt="u", schema=_Tiny)
    assert result.x == 1
    assert captured["reasoning_effort"] == "none"
    assert "temperature" not in captured


def test_luna_does_not_infer_minimal_reasoning_effort(monkeypatch) -> None:
    monkeypatch.setattr("app.services.usage_recorder.record_llm_usage", lambda **_k: None)
    captured: dict = {}

    class Completions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
                choices=[SimpleNamespace(message=SimpleNamespace(content='{"x": 1}'))],
            )

    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    provider = OpenAIStructuredProvider(api_key="k", model="gpt-5.6-luna", client=client)
    result = provider.generate_structured(system_prompt="s", user_prompt="u", schema=_Tiny)
    assert result.x == 1
    assert "reasoning_effort" not in captured


def test_nano_sends_minimal_reasoning_effort(monkeypatch) -> None:
    monkeypatch.setattr("app.services.usage_recorder.record_llm_usage", lambda **_k: None)
    captured: dict = {}

    class Completions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
                choices=[SimpleNamespace(message=SimpleNamespace(content='{"x": 1}'))],
            )

    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    provider = OpenAIStructuredProvider(api_key="k", model="gpt-5-nano", client=client)
    result = provider.generate_structured(system_prompt="s", user_prompt="u", schema=_Tiny)
    assert result.x == 1
    assert captured["reasoning_effort"] == "minimal"
    assert "temperature" not in captured
    assert captured["response_format"]["type"] == "json_schema"


def test_pydantic_retry_includes_schema_errors(monkeypatch) -> None:
    monkeypatch.setattr("app.services.usage_recorder.record_llm_usage", lambda **_k: None)
    calls: list[dict] = []

    class Completions:
        def create(self, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                content = "{}"
            else:
                content = '{"x": 1}'
            return SimpleNamespace(
                usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
                choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            )

    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    provider = OpenAIStructuredProvider(api_key="k", model="gpt-4o-mini", client=client)
    result = provider.generate_structured(system_prompt="s", user_prompt="u", schema=_Tiny)
    assert result.x == 1
    assert len(calls) == 2
    feedback = calls[1]["messages"][-1]["content"]
    assert "no cumplió el esquema" in feedback
    assert "x" in feedback


def test_json_schema_falls_back_to_json_object(monkeypatch) -> None:
    recorded: list[dict] = []
    monkeypatch.setattr("app.services.usage_recorder.record_llm_usage", lambda **kwargs: recorded.append(kwargs))
    formats: list[str] = []

    class Completions:
        def create(self, **kwargs):
            kind = kwargs["response_format"]["type"]
            formats.append(kind)
            if kind == "json_schema":
                import httpx
                from openai import BadRequestError

                request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
                response = httpx.Response(
                    400,
                    request=request,
                    json={"error": {"message": "json_schema not supported"}},
                )
                raise BadRequestError(
                    "Invalid response_format json_schema",
                    response=response,
                    body={"error": {"message": "json_schema not supported"}},
                )
            return SimpleNamespace(
                usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
                choices=[SimpleNamespace(message=SimpleNamespace(content='{"x": 2}'))],
            )

    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    provider = OpenAIStructuredProvider(api_key="k", model="gpt-4o-mini", client=client)
    result = provider.generate_structured(system_prompt="s", user_prompt="u", schema=_Tiny)
    assert result.x == 2
    assert formats == ["json_schema", "json_object"]
    assert len(recorded) == 2
    assert recorded[0]["failed"] is True
    assert recorded[0]["usage_reported"] is False
    assert recorded[1].get("failed") is not True
    assert recorded[1]["prompt_tokens"] == 1
