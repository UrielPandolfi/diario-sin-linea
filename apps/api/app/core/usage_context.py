from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, replace
from typing import Iterator
from uuid import UUID


@dataclass(frozen=True, slots=True)
class UsageContext:
    stage: str | None = None
    model_role: str | None = None
    provider: str | None = None
    event_id: UUID | None = None
    source_item_id: UUID | None = None
    pipeline_run_id: UUID | None = None


_CTX: ContextVar[UsageContext] = ContextVar("llm_usage_context", default=UsageContext())


def get_usage_context() -> UsageContext:
    return _CTX.get()


def bind_model_role(model_role: str, *, provider: str | None = None) -> Token[UsageContext]:
    current = _CTX.get()
    return _CTX.set(
        replace(
            current,
            model_role=model_role,
            provider=provider if provider is not None else current.provider,
        )
    )


def update_usage_context(**kwargs: object) -> Token[UsageContext]:
    current = _CTX.get()
    return _CTX.set(replace(current, **kwargs))  # type: ignore[arg-type]


def reset_usage_context(token: Token[UsageContext]) -> None:
    _CTX.reset(token)


@contextmanager
def usage_scope(
    *,
    stage: str,
    event_id: UUID | None = None,
    source_item_id: UUID | None = None,
    pipeline_run_id: UUID | None = None,
    model_role: str | None = None,
    provider: str | None = None,
) -> Iterator[None]:
    token = _CTX.set(
        UsageContext(
            stage=stage,
            event_id=event_id,
            source_item_id=source_item_id,
            pipeline_run_id=pipeline_run_id,
            model_role=model_role,
            provider=provider,
        )
    )
    try:
        yield
    finally:
        _CTX.reset(token)
