from types import SimpleNamespace

import httpx
import pytest
from openai import RateLimitError
from pydantic import BaseModel

from app.providers.openai_provider import OpenAIStructuredProvider
from app.providers.rate_limit import (
    is_quota_error,
    is_transient_rate_limit,
    parse_retry_after,
    retry_wait_seconds,
    with_rate_limit_retry,
)


class _Tiny(BaseModel):
    x: int


def _rate_limit_error(
    *,
    message: str,
    code: str = "rate_limit_exceeded",
    retry_after: str | None = None,
) -> RateLimitError:
    headers = {}
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    payload = {"error": {"message": message, "type": code, "code": code}}
    response = httpx.Response(429, request=request, headers=headers, json=payload)
    return RateLimitError(message, response=response, body=payload)


def test_parse_retry_after_seconds_and_http_date() -> None:
    assert parse_retry_after("19") == 19.0
    assert parse_retry_after("19.908") == 19.908
    assert parse_retry_after("nope") is None


def test_retry_after_header_wins_over_message() -> None:
    exc = _rate_limit_error(
        message="Rate limit reached for gpt-4o. Please try again in 19.908s.",
        retry_after="20",
    )
    assert retry_wait_seconds(exc, attempt=1) == 20.0


def test_message_wait_when_header_missing() -> None:
    exc = _rate_limit_error(
        message="Rate limit reached for gpt-4o. Please try again in 19.908s.",
    )
    assert retry_wait_seconds(exc, attempt=1) == 19.908


def test_backoff_when_no_wait_indicated() -> None:
    exc = _rate_limit_error(message="Rate limit reached for gpt-4o.")
    assert retry_wait_seconds(exc, attempt=1) == 1.0
    assert retry_wait_seconds(exc, attempt=2) == 2.0
    assert retry_wait_seconds(exc, attempt=3) == 4.0


def test_quota_is_not_transient() -> None:
    exc = _rate_limit_error(
        message="You exceeded your current quota",
        code="insufficient_quota",
        retry_after="1",
    )
    assert is_quota_error(exc) is True
    assert is_transient_rate_limit(exc) is False


def test_retry_then_success(monkeypatch) -> None:
    monkeypatch.setattr("app.providers.rate_limit.get_settings", lambda: SimpleNamespace(job_max_retries=3))
    monkeypatch.setattr("app.providers.rate_limit._jitter", lambda wait: 0.1)
    delays: list[float] = []
    calls = {"n": 0}

    def call():
        calls["n"] += 1
        if calls["n"] == 1:
            raise _rate_limit_error(
                message="Rate limit reached for gpt-4o. Please try again in 19.908s.",
                retry_after="20",
            )
        return "ok"

    assert with_rate_limit_retry(call, sleeper=delays.append) == "ok"
    assert calls["n"] == 2
    assert delays == [20.1]


def test_retries_exhausted(monkeypatch) -> None:
    monkeypatch.setattr("app.providers.rate_limit.get_settings", lambda: SimpleNamespace(job_max_retries=1))
    monkeypatch.setattr("app.providers.rate_limit._jitter", lambda wait: 0.0)
    delays: list[float] = []
    calls = {"n": 0}

    def call():
        calls["n"] += 1
        raise _rate_limit_error(message="Rate limit reached for gpt-4o.", retry_after="2")

    with pytest.raises(RateLimitError):
        with_rate_limit_retry(call, sleeper=delays.append)
    assert calls["n"] == 2
    assert delays == [2.0]


def test_insufficient_quota_does_not_retry(monkeypatch) -> None:
    delays: list[float] = []
    calls = {"n": 0}

    def call():
        calls["n"] += 1
        raise _rate_limit_error(
            message="You exceeded your current quota",
            code="insufficient_quota",
            retry_after="1",
        )

    with pytest.raises(RateLimitError):
        with_rate_limit_retry(call, sleeper=delays.append)
    assert calls["n"] == 1
    assert delays == []


def test_provider_retries_429_then_succeeds(monkeypatch) -> None:
    monkeypatch.setattr("app.services.usage_recorder.record_llm_usage", lambda **_k: None)
    monkeypatch.setattr("app.providers.rate_limit.get_settings", lambda: SimpleNamespace(job_max_retries=3))
    monkeypatch.setattr("app.providers.rate_limit._jitter", lambda wait: 0.0)
    delays: list[float] = []
    monkeypatch.setattr("app.providers.rate_limit.time.sleep", delays.append)
    outcomes = [
        _rate_limit_error(
            message="Rate limit reached for gpt-4o. Please try again in 19.908s.",
            retry_after="20",
        ),
        '{"x": 1}',
    ]

    class Completions:
        def create(self, **kwargs):
            item = outcomes.pop(0)
            if isinstance(item, Exception):
                raise item
            return SimpleNamespace(
                usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
                choices=[SimpleNamespace(message=SimpleNamespace(content=item))],
            )

    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    provider = OpenAIStructuredProvider(api_key="k", model="gpt-4o", client=client)
    result = provider.generate_structured(system_prompt="s", user_prompt="u", schema=_Tiny)
    assert result.x == 1
    assert delays == [20.0]
