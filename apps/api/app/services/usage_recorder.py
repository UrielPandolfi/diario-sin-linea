from __future__ import annotations

import logging
from contextlib import nullcontext
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import and_, or_, update
from sqlalchemy.orm import Session

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
    reasoning_tokens: int = 0
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
    completion_details = _attr_or_key(usage, "completion_tokens_details", "output_tokens_details")
    reasoning = _as_int(_attr_or_key(completion_details, "reasoning_tokens"))
    return ExtractedUsage(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total,
        cache_read_tokens=cache_read,
        cache_write_tokens=cache_write,
        reasoning_tokens=reasoning,
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


def _usage_fk_variants(payload: dict, kind: str) -> list[dict]:
    """La sesión de gasto no ve filas sin commit. Se conserva event_id si el run es el que falta."""
    variants = [dict(payload)]
    if payload.get("pipeline_run_id") is not None:
        dropped_run = dict(payload)
        dropped_run["pipeline_run_id"] = None
        variants.append(dropped_run)
    if payload.get("event_id") is not None or payload.get("pipeline_run_id") is not None:
        dropped_both = dict(payload)
        dropped_both["event_id"] = None
        dropped_both["pipeline_run_id"] = None
        if kind != ATTRIBUTION_EMBEDDING_BACKFILL:
            dropped_both["attribution_kind"] = infer_attribution_kind(
                event_id=None,
                source_item_id=dropped_both.get("source_item_id"),
                explicit=None if kind == ATTRIBUTION_DIRECT else kind,
            )
        variants.append(dropped_both)
    unique: list[dict] = []
    seen: list[tuple] = []
    for row in variants:
        key = (row.get("event_id"), row.get("pipeline_run_id"), row.get("attribution_kind"))
        if key in seen:
            continue
        seen.append(key)
        unique.append(row)
    return unique


def attach_pipeline_run_usages(session: Session, pipeline_run_id: UUID) -> None:
    """Sella el run en la misma transacción editorial. Si esa transacción vuelve atrás, el gasto queda."""
    session.execute(
        update(LlmUsage)
        .where(
            LlmUsage.pipeline_run_id.is_(None),
            LlmUsage.request_options["intended_pipeline_run_id"].astext == str(pipeline_run_id),
        )
        .values(pipeline_run_id=pipeline_run_id)
    )


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
    reasoning_tokens: int = 0,
    model_reported: str | None = None,
    usage_reported: bool | None = None,
    attribution_kind: str | None = None,
    failed: bool = False,
    call_kind: str = "llm",
    attempt_index: int = 1,
    request_options: dict | None = None,
    confirmed_cost_usd=None,
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
        # Búsqueda e imagen se cobran por pedido, sin tokens. Un éxito vacío igual se guarda.
        if empty and elapsed is None and not failed and (call_kind or "llm") not in {"search", "image"}:
            return
        resolved_event = event_id if event_id is not None else ctx.event_id
        resolved_item = source_item_id if source_item_id is not None else ctx.source_item_id
        kind = infer_attribution_kind(
            event_id=resolved_event,
            source_item_id=resolved_item,
            explicit=attribution_kind if attribution_kind is not None else ctx.attribution_kind,
        )

        from decimal import Decimal

        from sqlalchemy.exc import IntegrityError

        from app.core.config import get_settings
        from app.core.db import SessionLocal

        resolved_run = pipeline_run_id if pipeline_run_id is not None else ctx.pipeline_run_id
        options = dict(request_options or {})
        if ctx.fallback_from and "fallback_from" not in options:
            options["fallback_from"] = ctx.fallback_from
        if resolved_run is not None:
            options.setdefault("intended_pipeline_run_id", str(resolved_run))
        if resolved_event is not None:
            options.setdefault("intended_event_id", str(resolved_event))
        confirmed = None if confirmed_cost_usd is None else Decimal(str(confirmed_cost_usd))
        payload = dict(
            event_id=resolved_event,
            source_item_id=resolved_item,
            pipeline_run_id=resolved_run,
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
            reasoning_tokens=max(0, int(reasoning_tokens or 0)),
            duration_ms=elapsed,
            usage_reported=reported and not failed,
            attribution_kind=kind,
            call_kind=call_kind or "llm",
            environment=(get_settings().usage_environment or "production").strip() or "production",
            attempt_index=max(1, int(attempt_index or 1)),
            request_options=options or None,
            confirmed_cost_usd=confirmed,
        )
        variants = _usage_fk_variants(payload, kind)
        for index, row_kwargs in enumerate(variants):
            session = SessionLocal()
            try:
                row = LlmUsage(**row_kwargs)
                apply_estimated_cost(session, row)
                session.add(row)
                session.commit()
                return
            except IntegrityError:
                session.rollback()
                if index == len(variants) - 1:
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
    session: Session | None = None,
) -> None:
    """Sella event_id solo en llamadas de la corrida que creó el suceso. No toca backfill."""
    try:
        from datetime import datetime

        own_session = session is None
        if own_session:
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
            nested = session.begin_nested() if not own_session else nullcontext()
            with nested:
                session.execute(
                    update(LlmUsage)
                    .where(
                        LlmUsage.event_id.is_(None),
                        LlmUsage.attribution_kind != ATTRIBUTION_EMBEDDING_BACKFILL,
                        bound,
                    )
                    .values(event_id=event_id, attribution_kind=ATTRIBUTION_DIRECT)
                )
                if own_session:
                    session.commit()
                else:
                    session.flush()
        except Exception:
            if own_session:
                session.rollback()
            raise
        finally:
            if own_session:
                session.close()
    except Exception:
        logger.exception("llm usage seal failed")
