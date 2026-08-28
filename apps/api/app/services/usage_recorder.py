from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from app.core.usage_context import get_usage_context
from app.models.llm_usage import LlmUsage

logger = logging.getLogger(__name__)


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def extract_openai_usage(response: Any) -> tuple[int, int, int]:
    usage = getattr(response, "usage", None)
    if usage is None and isinstance(response, dict):
        usage = response.get("usage")
    if usage is None:
        return 0, 0, 0
    if isinstance(usage, dict):
        prompt = _as_int(usage.get("prompt_tokens") or usage.get("input_tokens"))
        completion = _as_int(usage.get("completion_tokens") or usage.get("output_tokens"))
        total = _as_int(usage.get("total_tokens")) or (prompt + completion)
        return prompt, completion, total
    prompt = _as_int(getattr(usage, "prompt_tokens", None) or getattr(usage, "input_tokens", None))
    completion = _as_int(
        getattr(usage, "completion_tokens", None) or getattr(usage, "output_tokens", None)
    )
    total = _as_int(getattr(usage, "total_tokens", None)) or (prompt + completion)
    return prompt, completion, total


def extract_anthropic_usage(response: Any) -> tuple[int, int, int]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return 0, 0, 0
    prompt = _as_int(getattr(usage, "input_tokens", None))
    completion = _as_int(getattr(usage, "output_tokens", None))
    return prompt, completion, prompt + completion


def record_llm_usage(
    *,
    provider: str,
    model: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int | None = None,
    event_id: UUID | None = None,
    source_item_id: UUID | None = None,
    pipeline_run_id: UUID | None = None,
    stage: str | None = None,
    model_role: str | None = None,
    duration_ms: int | None = None,
) -> None:
    """Best-effort persist; never raise into the LLM call path."""
    try:
        ctx = get_usage_context()
        prompt = max(0, int(prompt_tokens or 0))
        completion = max(0, int(completion_tokens or 0))
        total = max(0, int(total_tokens if total_tokens is not None else prompt + completion))
        elapsed = None if duration_ms is None else max(0, int(duration_ms))
        if prompt == 0 and completion == 0 and total == 0 and elapsed is None:
            return

        from app.core.db import SessionLocal

        payload = dict(
            event_id=event_id if event_id is not None else ctx.event_id,
            source_item_id=source_item_id if source_item_id is not None else ctx.source_item_id,
            pipeline_run_id=pipeline_run_id if pipeline_run_id is not None else ctx.pipeline_run_id,
            stage=stage if stage is not None else ctx.stage,
            model_role=model_role if model_role is not None else ctx.model_role,
            provider=provider or ctx.provider,
            model=model,
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=total,
            duration_ms=elapsed,
        )
        # Otra sesión no ve event/pipeline_run todavía no commiteados: reintentar sin esos FK.
        for drop_uncommitted_fks in (False, True):
            row_kwargs = dict(payload)
            if drop_uncommitted_fks:
                row_kwargs["event_id"] = None
                row_kwargs["pipeline_run_id"] = None
            session = SessionLocal()
            try:
                session.add(LlmUsage(**row_kwargs))
                session.commit()
                return
            except Exception:
                session.rollback()
                if drop_uncommitted_fks:
                    raise
            finally:
                session.close()
    except Exception:
        logger.exception("llm usage record failed")
