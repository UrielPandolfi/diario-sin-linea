"""Estimación de costo LLM: libro versionado + snapshot por llamada. No es factura."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import utc_now
from app.models.llm_price import LlmPriceBook, LlmPriceRate
from app.models.llm_usage import LlmUsage

ATTRIBUTION_DIRECT = "direct"
ATTRIBUTION_ITEM = "item"
ATTRIBUTION_UNATTRIBUTED = "unattributed"
ATTRIBUTION_EMBEDDING_BACKFILL = "embedding_backfill"

COST_CALCULATED = "calculated"
COST_PARTIAL = "partial"
COST_UNKNOWN = "unknown"

KIND_INPUT = "input"
KIND_OUTPUT = "output"
KIND_CACHED_READ = "cached_read"
KIND_CACHED_WRITE = "cached_write"
KIND_EMBEDDING = "embedding"

LUNA_LONG_CONTEXT_TOKENS = 272_000
MILLION = Decimal("1000000")

# Verificado 2026-09-08:
# gpt-4o / gpt-4o-mini / gpt-5-nano / gpt-5.6-luna: developers.openai.com (modelos + pricing)
# voyage-3: docs.voyageai.com/docs/pricing (modelos anteriores)
OFFICIAL_PRICE_BOOK = {
    "version": "2026-09-08",
    "effective_from": datetime(2026, 9, 8, tzinfo=timezone.utc),
    "source_url": "https://developers.openai.com/api/docs/pricing",
    "notes": (
        "Semilla solo con ids verificados. gpt-4o: $2.50/$1.25/$10.00. "
        "gpt-4o-mini: $0.15/$0.075/$0.60. gpt-5-nano: $0.05/$0.005/$0.40. "
        "gpt-5.6-luna corto: $0.20/$0.02/$1.20; cache writes 1.25× input; "
        ">272k input: 2× input y 1.5× output del request. "
        "voyage-3: $0.06/1M (docs Voyage, modelos anteriores). "
        "Sin DeepSeek ni ids no documentados."
    ),
    "rates": [
        ("openai", "gpt-4o", KIND_INPUT, "2.50"),
        ("openai", "gpt-4o", KIND_CACHED_READ, "1.25"),
        ("openai", "gpt-4o", KIND_OUTPUT, "10.00"),
        ("openai", "gpt-4o-mini", KIND_INPUT, "0.15"),
        ("openai", "gpt-4o-mini", KIND_CACHED_READ, "0.075"),
        ("openai", "gpt-4o-mini", KIND_OUTPUT, "0.60"),
        ("openai", "gpt-5-nano", KIND_INPUT, "0.05"),
        ("openai", "gpt-5-nano", KIND_CACHED_READ, "0.005"),
        ("openai", "gpt-5-nano", KIND_OUTPUT, "0.40"),
        ("openai", "gpt-5.6-luna", KIND_INPUT, "0.20"),
        ("openai", "gpt-5.6-luna", KIND_CACHED_READ, "0.02"),
        ("openai", "gpt-5.6-luna", KIND_CACHED_WRITE, "0.25"),
        ("openai", "gpt-5.6-luna", KIND_OUTPUT, "1.20"),
        ("voyage", "voyage-3", KIND_EMBEDDING, "0.06"),
    ],
}


def infer_attribution_kind(
    *,
    event_id: UUID | None,
    source_item_id: UUID | None,
    explicit: str | None = None,
) -> str:
    if explicit in {
        ATTRIBUTION_DIRECT,
        ATTRIBUTION_ITEM,
        ATTRIBUTION_UNATTRIBUTED,
        ATTRIBUTION_EMBEDDING_BACKFILL,
    }:
        return explicit
    if event_id is not None:
        return ATTRIBUTION_DIRECT
    if source_item_id is not None:
        return ATTRIBUTION_ITEM
    return ATTRIBUTION_UNATTRIBUTED


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.0000000001"), rounding=ROUND_HALF_UP)


def _dec(value: Any) -> Decimal:
    return Decimal(str(value))


def _model_key(value: str | None) -> str:
    return (value or "").strip().casefold()


def active_price_book(session: Session, *, at: datetime | None = None) -> LlmPriceBook | None:
    moment = at or utc_now()
    return session.scalars(
        select(LlmPriceBook)
        .where(LlmPriceBook.effective_from <= moment)
        .order_by(LlmPriceBook.effective_from.desc(), LlmPriceBook.created_at.desc())
        .limit(1)
    ).first()


def rates_map(session: Session, book: LlmPriceBook) -> dict[tuple[str, str, str], Decimal]:
    rows = session.scalars(select(LlmPriceRate).where(LlmPriceRate.book_id == book.id)).all()
    return {
        (_model_key(row.provider), _model_key(row.model), row.kind): row.usd_per_million
        for row in rows
    }


def _lookup_model(
    rates: dict[tuple[str, str, str], Decimal],
    provider: str | None,
    model_reported: str | None,
    model_requested: str | None,
) -> tuple[str | None, dict[str, Decimal]]:
    provider_key = _model_key(provider)
    for candidate in (model_reported, model_requested):
        model_key = _model_key(candidate)
        if not provider_key or not model_key:
            continue
        found = {
            kind: amount
            for (prov, model, kind), amount in rates.items()
            if prov == provider_key and model == model_key
        }
        if found:
            return candidate, found
    return None, {}


@dataclass(frozen=True)
class CostEstimate:
    status: str
    usd: Decimal | None
    snapshot: dict[str, Any]
    priced_model: str | None


def estimate_usage_cost(
    *,
    provider: str | None,
    model_requested: str | None,
    model_reported: str | None,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    cache_read_tokens: int,
    cache_write_tokens: int,
    usage_reported: bool,
    rates: dict[tuple[str, str, str], Decimal],
    book_id: UUID | None,
) -> CostEstimate:
    snapshot: dict[str, Any] = {
        "provider": provider,
        "model_requested": model_requested,
        "model_reported": model_reported,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "cache_read_tokens": cache_read_tokens,
        "cache_write_tokens": cache_write_tokens,
        "usage_reported": usage_reported,
        "price_book_id": str(book_id) if book_id else None,
    }
    if not usage_reported or (
        prompt_tokens == 0
        and completion_tokens == 0
        and total_tokens == 0
        and cache_read_tokens == 0
        and cache_write_tokens == 0
    ):
        snapshot["reason"] = "no_billable_tokens"
        return CostEstimate(COST_UNKNOWN, None, snapshot, None)

    priced_model, found = _lookup_model(rates, provider, model_reported, model_requested)
    snapshot["priced_model"] = priced_model
    if not found:
        snapshot["reason"] = "no_verified_rate"
        return CostEstimate(COST_UNKNOWN, None, snapshot, None)

    provider_key = _model_key(provider)
    usd = Decimal("0")
    partial = False
    used_kinds: dict[str, str] = {kind: str(amount) for kind, amount in found.items()}
    snapshot["rates_used"] = used_kinds

    if provider_key == "voyage" or KIND_EMBEDDING in found:
        if KIND_EMBEDDING not in found:
            snapshot["reason"] = "missing_embedding_rate"
            return CostEstimate(COST_UNKNOWN, None, snapshot, priced_model)
        embed_tokens = total_tokens or prompt_tokens
        usd += _dec(embed_tokens) * found[KIND_EMBEDDING] / MILLION
        snapshot["formula"] = "embedding"
        snapshot["embedding_tokens"] = embed_tokens
        return CostEstimate(COST_CALCULATED, _money(usd), snapshot, priced_model)

    if provider_key == "anthropic":
        if KIND_INPUT not in found or KIND_OUTPUT not in found:
            snapshot["reason"] = "missing_io_rate"
            return CostEstimate(COST_UNKNOWN, None, snapshot, priced_model)
        usd += _dec(prompt_tokens) * found[KIND_INPUT] / MILLION
        usd += _dec(completion_tokens) * found[KIND_OUTPUT] / MILLION
        if cache_read_tokens:
            if KIND_CACHED_READ in found:
                usd += _dec(cache_read_tokens) * found[KIND_CACHED_READ] / MILLION
            else:
                partial = True
        if cache_write_tokens:
            if KIND_CACHED_WRITE in found:
                usd += _dec(cache_write_tokens) * found[KIND_CACHED_WRITE] / MILLION
            else:
                partial = True
        snapshot["formula"] = "anthropic_input_plus_cache_plus_output"
        status = COST_PARTIAL if partial else COST_CALCULATED
        return CostEstimate(status, _money(usd), snapshot, priced_model)

    # OpenAI y similares: uncached = prompt - cache_read (sin doble conteo).
    if KIND_INPUT not in found or KIND_OUTPUT not in found:
        snapshot["reason"] = "missing_io_rate"
        return CostEstimate(COST_UNKNOWN, None, snapshot, priced_model)
    cache_read = max(0, min(int(cache_read_tokens or 0), int(prompt_tokens or 0)))
    uncached = max(0, int(prompt_tokens or 0) - cache_read)
    input_rate = found[KIND_INPUT]
    output_rate = found[KIND_OUTPUT]
    cached_rate = found.get(KIND_CACHED_READ)
    write_rate = found.get(KIND_CACHED_WRITE)
    long_context = _model_key(priced_model).startswith("gpt-5.6-luna") and prompt_tokens > LUNA_LONG_CONTEXT_TOKENS
    if long_context:
        input_rate = input_rate * Decimal("2")
        output_rate = output_rate * Decimal("1.5")
        if cached_rate is not None:
            cached_rate = cached_rate * Decimal("2")
        if write_rate is not None:
            write_rate = write_rate * Decimal("2")
        snapshot["long_context"] = True
        snapshot["long_context_rule"] = "luna_>272k_2x_input_1.5x_output"
    usd += _dec(uncached) * input_rate / MILLION
    if cache_read:
        if cached_rate is None:
            partial = True
        else:
            usd += _dec(cache_read) * cached_rate / MILLION
    usd += _dec(completion_tokens) * output_rate / MILLION
    if cache_write_tokens:
        if write_rate is None:
            partial = True
        else:
            usd += _dec(cache_write_tokens) * write_rate / MILLION
    snapshot["formula"] = "openai_uncached_plus_cached_plus_output"
    snapshot["uncached_prompt_tokens"] = uncached
    snapshot["input_rate"] = str(input_rate)
    snapshot["output_rate"] = str(output_rate)
    if cached_rate is not None:
        snapshot["cached_read_rate"] = str(cached_rate)
    if write_rate is not None:
        snapshot["cached_write_rate"] = str(write_rate)
    status = COST_PARTIAL if partial else COST_CALCULATED
    return CostEstimate(status, _money(usd), snapshot, priced_model)


def apply_estimated_cost(session: Session, row: LlmUsage) -> LlmUsage:
    book = active_price_book(session)
    rates = rates_map(session, book) if book is not None else {}
    estimate = estimate_usage_cost(
        provider=row.provider,
        model_requested=row.model_requested or row.model,
        model_reported=row.model_reported,
        prompt_tokens=int(row.prompt_tokens or 0),
        completion_tokens=int(row.completion_tokens or 0),
        total_tokens=int(row.total_tokens or 0),
        cache_read_tokens=int(row.cache_read_tokens or 0),
        cache_write_tokens=int(row.cache_write_tokens or 0),
        usage_reported=bool(row.usage_reported),
        rates=rates,
        book_id=book.id if book is not None else None,
    )
    row.price_book_id = book.id if book is not None else None
    row.cost_status = estimate.status
    row.estimated_cost_usd = estimate.usd
    row.rate_snapshot = estimate.snapshot
    return row


def coverage_payload(*, calculated: int, partial: int, unknown: int, known_usd: Decimal) -> dict[str, Any]:
    total = calculated + partial + unknown
    ratio = (calculated / total) if total else 1.0
    return {
        "calculated_calls": calculated,
        "partial_calls": partial,
        "unknown_calls": unknown,
        "total_calls": total,
        "calculated_ratio": ratio,
        "complete": unknown == 0 and partial == 0,
        "label": "completo" if unknown == 0 and partial == 0 else "parcial",
        "subtotal_known_usd": float(_money(known_usd)),
        "subtotal_is_total_spend": unknown == 0 and partial == 0,
    }


def aggregate_usage_costs(
    session: Session,
    *,
    since: datetime,
    until: datetime | None = None,
    event_id: UUID | None = None,
    exclude_backfill: bool = False,
) -> dict[str, Any]:
    stmt = select(LlmUsage).where(LlmUsage.created_at >= since)
    if until is not None:
        stmt = stmt.where(LlmUsage.created_at < until)
    if event_id is not None:
        stmt = stmt.where(LlmUsage.event_id == event_id)
        if exclude_backfill:
            stmt = stmt.where(LlmUsage.attribution_kind != ATTRIBUTION_EMBEDDING_BACKFILL)
    rows = list(session.scalars(stmt))
    by_kind: dict[str, dict[str, Any]] = {}
    by_status = {COST_CALCULATED: 0, COST_PARTIAL: 0, COST_UNKNOWN: 0}
    known = Decimal("0")
    prompt = completion = total = 0
    for row in rows:
        kind = row.attribution_kind or ATTRIBUTION_UNATTRIBUTED
        bucket = by_kind.setdefault(
            kind,
            {"calls": 0, "known_usd": Decimal("0"), "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        )
        bucket["calls"] += 1
        bucket["prompt_tokens"] += int(row.prompt_tokens or 0)
        bucket["completion_tokens"] += int(row.completion_tokens or 0)
        bucket["total_tokens"] += int(row.total_tokens or 0)
        status = row.cost_status or COST_UNKNOWN
        by_status[status] = by_status.get(status, 0) + 1
        if status == COST_CALCULATED and row.estimated_cost_usd is not None:
            amount = _dec(row.estimated_cost_usd)
            known += amount
            bucket["known_usd"] += amount
        prompt += int(row.prompt_tokens or 0)
        completion += int(row.completion_tokens or 0)
        total += int(row.total_tokens or 0)

    global_usd = known
    attributed = by_kind.get(ATTRIBUTION_DIRECT, {}).get("known_usd", Decimal("0"))
    item_only = by_kind.get(ATTRIBUTION_ITEM, {}).get("known_usd", Decimal("0"))
    unattributed = by_kind.get(ATTRIBUTION_UNATTRIBUTED, {}).get("known_usd", Decimal("0"))
    backfill = by_kind.get(ATTRIBUTION_EMBEDDING_BACKFILL, {}).get("known_usd", Decimal("0"))
    parts = attributed + item_only + unattributed + backfill

    return {
        "timestamp_field": "llm_usages.created_at",
        "timestamp_label": "alta de la llamada",
        "since": since.isoformat(),
        "until": until.isoformat() if until else None,
        "calls": len(rows),
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
        "subtotal_known_usd": float(_money(known)),
        "coverage": coverage_payload(
            calculated=by_status.get(COST_CALCULATED, 0),
            partial=by_status.get(COST_PARTIAL, 0),
            unknown=by_status.get(COST_UNKNOWN, 0),
            known_usd=known,
        ),
        "by_attribution_kind": {
            kind: {
                "calls": bucket["calls"],
                "known_usd": float(_money(bucket["known_usd"])),
                "prompt_tokens": bucket["prompt_tokens"],
                "completion_tokens": bucket["completion_tokens"],
                "total_tokens": bucket["total_tokens"],
            }
            for kind, bucket in by_kind.items()
        },
        "reconciliation": {
            "global_known_usd": float(_money(global_usd)),
            "attributed_to_event": float(_money(attributed)),
            "attributed_to_item_only": float(_money(item_only)),
            "unattributed": float(_money(unattributed)),
            "embedding_backfill": float(_money(backfill)),
            "parts_sum_usd": float(_money(parts)),
            "matches_global": _money(parts) == _money(global_usd),
        },
    }


def event_direct_cost(session: Session, event_id: UUID) -> dict[str, Any]:
    stmt = select(LlmUsage).where(
        LlmUsage.event_id == event_id,
        LlmUsage.attribution_kind != ATTRIBUTION_EMBEDDING_BACKFILL,
    )
    rows = list(session.scalars(stmt))
    known = Decimal("0")
    by_status = {COST_CALCULATED: 0, COST_PARTIAL: 0, COST_UNKNOWN: 0}
    prompt = completion = total = 0
    duration_total = 0
    duration_calls = 0
    for row in rows:
        status = row.cost_status or COST_UNKNOWN
        by_status[status] = by_status.get(status, 0) + 1
        if status == COST_CALCULATED and row.estimated_cost_usd is not None:
            known += _dec(row.estimated_cost_usd)
        prompt += int(row.prompt_tokens or 0)
        completion += int(row.completion_tokens or 0)
        total += int(row.total_tokens or 0)
        if row.duration_ms is not None:
            duration_total += int(row.duration_ms)
            duration_calls += 1
    return {
        "direct_only": True,
        "backfill_excluded": True,
        "calls": len(rows),
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
        "duration_ms_sum": duration_total if duration_calls else None,
        "subtotal_known_usd": float(_money(known)),
        "coverage": coverage_payload(
            calculated=by_status.get(COST_CALCULATED, 0),
            partial=by_status.get(COST_PARTIAL, 0),
            unknown=by_status.get(COST_UNKNOWN, 0),
            known_usd=known,
        ),
    }
