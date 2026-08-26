from app.providers.openai_provider import _model_allows_temperature_zero


def test_temperature_zero_allowed_for_standard_models() -> None:
    assert _model_allows_temperature_zero("gpt-4o-mini") is True
    assert _model_allows_temperature_zero("gpt-4o") is True
    assert _model_allows_temperature_zero("gpt-4.1-mini") is True


def test_temperature_zero_blocked_for_reasoning_style_models() -> None:
    assert _model_allows_temperature_zero("gpt-5.6-luna") is False
    assert _model_allows_temperature_zero("gpt-5") is False
    assert _model_allows_temperature_zero("o3-mini") is False
    assert _model_allows_temperature_zero("o1") is False
