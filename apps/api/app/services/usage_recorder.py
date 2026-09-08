from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import and_, or_, update

from app.core.usage_context import get_usage_context
from app.models.llm_usage import LlmUsage
from app.services.cost_service import (
    ATTRIBUTION_DIRECT,
    ATTRIBUTION_EMBEDDING_BACKFILL,
    apply_estimated_cost,
    infer_attribution_kind,
)

logger = logging.getLogger(__name__)


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _attr_or_key(obj: Any, *names: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        for name in names:
            if name in obj and obj[name] is not None:
                return obj[name]
        return None
    for name in names:
        value = getattr(obj, name, None)
        if value is not None:
            return value
    return None


@dataclass(frozen=True)
class ExtractedUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    model_reported: str | None = None
    usage_reported: bool = False


def extract_reported_model(response: Any) -> str | None:
    value = _attr_or_key(response, "model")
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def extract_openai_usage_details(response: Any) -> ExtractedUsage:
    usage = _attr_or_key(response, "usage")
    model_reported = extract_reported_model(response)
    if usage is None:
        return ExtractedUsage(model_reported=model_reported, usage_reported=False)
    prompt = _as_int(_attr_or_key(usage, "prompt_tokens", "input_tokens"))
    completion = _as_int(_attr_or_key(usage, "completion_tokens", "output_tokens"))
    total = _as_int(_attr_or_key(usage, "total_tokens")) or (prompt + completion)
    details = _attr_or_key(usage, "prompt_tokens_details", "input_tokens_details")
    cache_read = _as_int(_attr_or_key(details, "cached_tokens", "cache_read_tokens"))
    cache_write = _as_int(
        _attr_or_key(
            usage,
            "cache_creation_tokens",
            "cache_creation_input_tokens",
        )
        or _attr_or_key(details, "cache_creation_tokens", "cache_write_tokens")
    )
    return ExtractedUsage(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total,
        cache_read_tokens=cache_read,
        cache_write_tokens=cache_write,
        model_reported=model_reported,
        usage_reported=True,
    )


def extract_openai_usage(response: Any) -> tuple[int, int, int]:
    details = extract_openai_usage_details(response)
    return details.prompt_tokens, details.completion_tokens, details.total_tokens


def extract_anthropic_usage_details(response: Any) -> ExtractedUsage:
    usage = _attr_or_key(response, "usage")
    model_reported = extract_reported_model(response)
    if usage is None:
        return ExtractedUsage(model_reported=model_reported, usage_reported=False)
    prompt = _as_int(_attr_or_key(usage, "input_tokens"))
    completion = _as_int(_attr_or_key(usage, "output_tokens"))
    cache_read = _as_int(_attr_or_key(usage, "cache_read_input_tokens"))
    cache_write = _as_int(_attr_or_key(usage, "cache_creation_input_tokens"))
    return ExtractedUsage(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=prompt + completion,
        cache_read_tokens=cache_read,
        cache_write_tokens=cache_write,
        model_reported=model_reported,
        usage_reported=True,
    )


def extract_anthropic_usage(response: Any) -> tuple[int, int, int]:
    details = extract_anthropic_usage_details(response)
    return details.prompt_tokens, details.completion_tokens, details.total_tokens


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
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    model_reported: str | None = None,
    usage_reported: bool | None = None,
    attribution_kind: str | None = None,
    failed: bool = False,
) -> None:
    """Best-effort persist; never raise into the LLM call path."""
    try:
        ctx = get_usage_context()
        prompt = max(0, int(prompt_tokens or 0))
        completion = max(0, int(completion_tokens or 0))
        total = max(0, int(total_tokens if total_tokens is not None else prompt + completion))
        cache_read = max(0, int(cache_read_tokens or 0))
        cache_write = max(0, int(cache_write_tokens or 0))
        elapsed = None if duration_ms is None else max(0, int(duration_ms))
        reported = bool(usage_reported) if usage_reported is not None else not failed
        empty = (
            prompt == 0
            and completion == 0
            and total == 0
            and cache_read == 0
            and cache_write == 0
        )
        if empty and elapsed is None and not failed:
            return
        resolved_event = event_id if event_id is not None else ctx.event_id
        resolved_item = source_item_id if source_item_id is not None else ctx.source_item_id
        kind = infer_attribution_kind(
            event_id=resolved_event,
            source_item_id=resolved_item,
            explicit=attribution_kind if attribution_kind is not None else ctx.attribution_kind,
        )

        from app.core.db import SessionLocal

        payload = dict(
            event_id=resolved_event,
            source_item_id=resolved_item,
            pipeline_run_id=pipeline_run_id if pipeline_run_id is not None else ctx.pipeline_run_id,
            stage=stage if stage is not None else ctx.stage,
            model_role=model_role if model_role is not None else ctx.model_role,
            provider=provider or ctx.provider,
            model=model,
            model_requested=model,
            model_reported=model_reported,
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=total,
            cache_read_tokens=cache_read,
            cache_write_tokens=cache_write,
            duration_ms=elapsed,
            usage_reported=reported and not failed,
            attribution_kind=kind,
        )
        # Otra sesión no ve event/pipeline_run todavía no commiteados: reintentar sin esos FK.
        for drop_uncommitted_fks in (False, True):
            row_kwargs = dict(payload)
            if drop_uncommitted_fks:
                row_kwargs["event_id"] = None
                row_kwargs["pipeline_run_id"] = None
                if kind != ATTRIBUTION_EMBEDDING_BACKFILL:
                    row_kwargs["attribution_kind"] = infer_attribution_kind(
                        event_id=None,
                        source_item_id=row_kwargs.get("source_item_id"),
                        explicit=None if kind == ATTRIBUTION_DIRECT else kind,
                    )
            session = SessionLocal()
            try:
                row = LlmUsage(**row_kwargs)
                apply_estimated_cost(session, row)
                session.add(row)
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


def seal_created_event_usages(
    pipeline_run_id: UUID,
    event_id: UUID,
    *,
    source_item_id: UUID | None = None,
    not_before=None,
) -> None:
    """Sella event_id solo en llamadas de la corrida que creó el suceso. No toca backfill."""
    try:
        from datetime import datetime

        from app.core.db import SessionLocal

        session = SessionLocal()
        try:
            match_run = LlmUsage.pipeline_run_id == pipeline_run_id
            match_item = None
            if source_item_id is not None:
                item_filters = [
                    LlmUsage.source_item_id == source_item_id,
                    LlmUsage.stage == "event_detection",
                ]
                if isinstance(not_before, datetime):
                    item_filters.append(LlmUsage.created_at >= not_before)
                match_item = and_(*item_filters)
            bound = match_run if match_item is None else or_(match_run, match_item)
            session.execute(
                update(LlmUsage)
                .where(
                    LlmUsage.event_id.is_(None),
                    LlmUsage.attribution_kind != ATTRIBUTION_EMBEDDING_BACKFILL,
                    bound,
                )
                .values(event_id=event_id, attribution_kind=ATTRIBUTION_DIRECT)
            )
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
    except Exception:
        logger.exception("llm usage seal failed")
