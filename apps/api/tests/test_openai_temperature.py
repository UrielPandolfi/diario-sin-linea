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


def test_reasoning_effort_minimal_for_nano_and_gpt5() -> None:
    assert _reasoning_effort_for_model("gpt-5-nano") == "minimal"
    assert _reasoning_effort_for_model("gpt-5") == "minimal"
    assert _reasoning_effort_for_model("gpt-4o-mini") is None
    assert _reasoning_effort_for_model("deepseek-v4-flash") is None


class _Tiny(BaseModel):
    x: int


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
