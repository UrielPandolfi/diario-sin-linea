from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.core.usage_context import attribution_scope, usage_scope
from app.domain.enums import EventSourceRelation, IngestionMethod, PipelineStatus
from app.models import EventSource, LlmUsage, PipelineRun
from app.schemas import EventCreate, SourceCreate, SourceItemCreate
from app.services.cost_service import (
    ATTRIBUTION_EMBEDDING_BACKFILL,
    ATTRIBUTION_ITEM,
    COST_CALCULATED,
    COST_UNKNOWN,
    KIND_CACHED_READ,
    KIND_INPUT,
    KIND_OUTPUT,
    aggregate_usage_costs,
    estimate_usage_cost,
    event_direct_cost,
)
from app.services.event_service import EventService
from app.services.source_item_service import SourceItemService
from app.services.source_service import SourceService
from app.services.usage_recorder import (
    extract_openai_usage_details,
    record_llm_usage,
    seal_created_event_usages,
)
from sqlalchemy import select
from types import SimpleNamespace


def test_extract_openai_cache_and_reported_model() -> None:
    response = SimpleNamespace(
        model="gpt-4o-mini-2024-07-18",
        usage=SimpleNamespace(
            prompt_tokens=100,
            completion_tokens=10,
            total_tokens=110,
            prompt_tokens_details=SimpleNamespace(cached_tokens=40),
        ),
    )
    details = extract_openai_usage_details(response)
    assert details.cache_read_tokens == 40
    assert details.model_reported == "gpt-4o-mini-2024-07-18"
    assert details.prompt_tokens == 100


def test_openai_uncached_does_not_double_count_cache() -> None:
    rates = {
        ("openai", "gpt-4o-mini", KIND_INPUT): Decimal("0.15"),
        ("openai", "gpt-4o-mini", KIND_CACHED_READ): Decimal("0.075"),
        ("openai", "gpt-4o-mini", KIND_OUTPUT): Decimal("0.60"),
    }
    estimate = estimate_usage_cost(
        provider="openai",
        model_requested="gpt-4o-mini",
        model_reported="gpt-4o-mini",
        prompt_tokens=100,
        completion_tokens=10,
        total_tokens=110,
        cache_read_tokens=40,
        cache_write_tokens=0,
        usage_reported=True,
        rates=rates,
        book_id=None,
    )
    assert estimate.status == COST_CALCULATED
    expected = (
        Decimal("60") * Decimal("0.15")
        + Decimal("40") * Decimal("0.075")
        + Decimal("10") * Decimal("0.60")
    ) / Decimal("1000000")
    assert estimate.usd == expected.quantize(Decimal("0.0000000001"))
    doubled = (
        Decimal("100") * Decimal("0.15")
        + Decimal("40") * Decimal("0.075")
        + Decimal("10") * Decimal("0.60")
    ) / Decimal("1000000")
    assert estimate.usd != doubled.quantize(Decimal("0.0000000001"))


def test_unknown_model_is_not_seeded() -> None:
    estimate = estimate_usage_cost(
        provider="openai",
        model_requested="deepseek-v4",
        model_reported=None,
        prompt_tokens=10,
        completion_tokens=2,
        total_tokens=12,
        cache_read_tokens=0,
        cache_write_tokens=0,
        usage_reported=True,
        rates={("openai", "gpt-4o-mini", KIND_INPUT): Decimal("0.15")},
        book_id=None,
    )
    assert estimate.status == COST_UNKNOWN
    assert estimate.usd is None


def _source_item_event(db_session: Session):
    source = SourceService(db_session).create(
        SourceCreate(
            name="Costos",
            preferred_ingestion_method=IngestionMethod.RSS,
            feed_url="https://c.test/rss",
            is_monitored=True,
            is_enabled=True,
        )
    )
    item = SourceItemService(db_session).ingest(
        SourceItemCreate(
            source_id=source.id,
            url="https://c.test/a",
            canonical_url="https://c.test/a",
            content_hash="c1",
            title="Nota",
            clean_text="cuerpo largo de la nota",
        )
    ).item
    event = EventService(db_session).create(
        EventCreate(
            title_internal="Suceso costo",
            event_type="otro",
            source_item_id=item.id,
            short_summary="s",
        )
    )
    db_session.commit()
    return item, event


def test_item_usage_does_not_fan_out_to_all_events(db_session: Session) -> None:
    item, event_a = _source_item_event(db_session)
    event_b = EventService(db_session).create(
        EventCreate(
            title_internal="Otro suceso",
            event_type="otro",
            short_summary="b",
        )
    )
    db_session.add(
        EventSource(
            event_id=event_b.id,
            source_item_id=item.id,
            relation_type=EventSourceRelation.CONFIRMING,
            is_primary=False,
        )
    )
    db_session.add(
        LlmUsage(
            source_item_id=item.id,
            stage="event_detection",
            provider="openai",
            model="gpt-4o-mini",
            model_requested="gpt-4o-mini",
            prompt_tokens=80,
            completion_tokens=20,
            total_tokens=100,
            attribution_kind=ATTRIBUTION_ITEM,
            cost_status=COST_CALCULATED,
            estimated_cost_usd=Decimal("0.01"),
            usage_reported=True,
        )
    )
    db_session.commit()
    assert event_direct_cost(db_session, event_a.id)["calls"] == 0
    assert event_direct_cost(db_session, event_b.id)["calls"] == 0
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    totals = aggregate_usage_costs(db_session, since=since)
    assert totals["calls"] == 1
    assert totals["reconciliation"]["matches_global"] is True
    assert totals["by_attribution_kind"][ATTRIBUTION_ITEM]["calls"] == 1


def test_backfill_is_not_sealed_to_triggering_event(db_session: Session) -> None:
    item, event = _source_item_event(db_session)
    run = PipelineRun(
        source_item_id=item.id,
        event_id=event.id,
        stage="event_detection",
        status=PipelineStatus.SUCCESS,
    )
    db_session.add(run)
    db_session.commit()
    with usage_scope(stage="event_detection", source_item_id=item.id, pipeline_run_id=run.id):
        with attribution_scope(ATTRIBUTION_EMBEDDING_BACKFILL):
            record_llm_usage(
                provider="voyage",
                model="voyage-3",
                prompt_tokens=50,
                completion_tokens=0,
                total_tokens=50,
                duration_ms=8,
            )
        record_llm_usage(
            provider="openai",
            model="gpt-4o-mini",
            prompt_tokens=10,
            completion_tokens=4,
            total_tokens=14,
            duration_ms=12,
        )
    seal_created_event_usages(run.id, event.id)
    db_session.expire_all()
    check = SessionLocal()
    try:
        rows = list(check.scalars(select(LlmUsage).where(LlmUsage.pipeline_run_id == run.id)))
        kinds = {row.attribution_kind: row for row in rows}
        assert ATTRIBUTION_EMBEDDING_BACKFILL in kinds
        assert kinds[ATTRIBUTION_EMBEDDING_BACKFILL].event_id is None
        assert kinds["direct"].event_id == event.id
    finally:
        check.close()
    direct = event_direct_cost(db_session, event.id)
    assert direct["calls"] == 1
    assert direct["backfill_excluded"] is True


def test_record_failed_usage_without_tokens(db_session: Session) -> None:
    record_llm_usage(
        provider="openai",
        model="gpt-4o-mini",
        prompt_tokens=0,
        completion_tokens=0,
        total_tokens=0,
        failed=True,
        usage_reported=False,
        stage="event_detection",
    )
    check = SessionLocal()
    try:
        rows = list(
            check.scalars(
                select(LlmUsage).where(
                    LlmUsage.model == "gpt-4o-mini",
                    LlmUsage.usage_reported.is_(False),
                )
            )
        )
        assert len(rows) == 1
        assert rows[0].cost_status == COST_UNKNOWN
        assert rows[0].estimated_cost_usd is None
    finally:
        check.close()


def test_seal_without_pipeline_fk_uses_item_and_stage(db_session: Session) -> None:
    item, event = _source_item_event(db_session)
    started = datetime.now(timezone.utc) - timedelta(seconds=5)
    record_llm_usage(
        provider="openai",
        model="gpt-4o-mini",
        prompt_tokens=12,
        completion_tokens=3,
        total_tokens=15,
        duration_ms=9,
        source_item_id=item.id,
        stage="event_detection",
        attribution_kind=ATTRIBUTION_ITEM,
    )
    seal_created_event_usages(uuid4(), event.id, source_item_id=item.id, not_before=started)
    db_session.expire_all()
    check = SessionLocal()
    try:
        row = check.scalars(
            select(LlmUsage).where(LlmUsage.source_item_id == item.id, LlmUsage.stage == "event_detection")
        ).first()
        assert row is not None
        assert row.event_id == event.id
        assert row.attribution_kind == "direct"
    finally:
        check.close()


def test_priced_mini_gets_snapshot(db_session: Session) -> None:
    record_llm_usage(
        provider="openai",
        model="gpt-4o-mini",
        model_reported="gpt-4o-mini",
        prompt_tokens=1000,
        completion_tokens=500,
        total_tokens=1500,
        duration_ms=20,
        stage="writing",
    )
    check = SessionLocal()
    try:
        row = check.scalars(select(LlmUsage).where(LlmUsage.stage == "writing")).first()
        assert row is not None
        assert row.cost_status == COST_CALCULATED
        assert row.estimated_cost_usd is not None
        assert row.rate_snapshot["formula"] == "openai_uncached_plus_cached_plus_output"
        assert row.price_book_id is not None
    finally:
        check.close()
