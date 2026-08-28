from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.usage_context import usage_scope
from app.domain.enums import IngestionMethod
from app.main import app
from app.models import LlmUsage
from app.repositories import LlmUsageRepository
from app.schemas import EventCreate, SourceCreate, SourceItemCreate
from app.services.event_service import EventService
from app.services.source_item_service import SourceItemService
from app.services.source_service import SourceService
from app.services.usage_recorder import extract_anthropic_usage, extract_openai_usage, record_llm_usage
from sqlalchemy import select


def test_extract_openai_and_anthropic_usage() -> None:
    openai_resp = SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    )
    assert extract_openai_usage(openai_resp) == (10, 5, 15)
    anthropic_resp = SimpleNamespace(usage=SimpleNamespace(input_tokens=7, output_tokens=3))
    assert extract_anthropic_usage(anthropic_resp) == (7, 3, 10)


def test_record_llm_usage_persists_with_context(db_session: Session) -> None:
    source = SourceService(db_session).create(
        SourceCreate(
            name="U",
            preferred_ingestion_method=IngestionMethod.RSS,
            feed_url="https://u.test/rss",
            is_monitored=True,
            is_enabled=True,
        )
    )
    item = SourceItemService(db_session).ingest(
        SourceItemCreate(
            source_id=source.id,
            url="https://u.test/a",
            canonical_url="https://u.test/a",
            content_hash="u1",
            title="T",
            clean_text="body",
        )
    ).item
    event = EventService(db_session).create(
        EventCreate(
            title_internal="Suceso usage",
            event_type="otro",
            source_item_id=item.id,
            short_summary="s",
        )
    )
    db_session.commit()

    with usage_scope(
        stage="writing",
        event_id=event.id,
        source_item_id=item.id,
        model_role="writing",
        provider="openai",
    ):
        record_llm_usage(
            provider="openai",
            model="gpt-4o-mini",
            prompt_tokens=100,
            completion_tokens=40,
            total_tokens=140,
            duration_ms=25,
        )

    check = SessionLocal()
    try:
        rows = list(check.scalars(select(LlmUsage).where(LlmUsage.event_id == event.id)))
        assert len(rows) == 1
        assert rows[0].prompt_tokens == 100
        assert rows[0].completion_tokens == 40
        assert rows[0].total_tokens == 140
        assert rows[0].duration_ms == 25
        assert rows[0].model_role == "writing"
        assert rows[0].stage == "writing"
    finally:
        check.close()


def test_record_llm_usage_keeps_zero_tokens_if_duration(db_session: Session) -> None:
    record_llm_usage(
        provider="openai",
        model="gpt-5-nano",
        prompt_tokens=0,
        completion_tokens=0,
        total_tokens=0,
        duration_ms=12,
        stage="event_detection",
        model_role="ultra_light_processing",
    )
    check = SessionLocal()
    try:
        rows = list(check.scalars(select(LlmUsage).where(LlmUsage.model == "gpt-5-nano")))
        assert len(rows) == 1
        assert rows[0].total_tokens == 0
        assert rows[0].duration_ms == 12
    finally:
        check.close()


def test_admin_stats_and_event_tokens(db_session: Session) -> None:
    settings = get_settings()
    source = SourceService(db_session).create(
        SourceCreate(
            name="S",
            preferred_ingestion_method=IngestionMethod.RSS,
            feed_url="https://s.test/rss",
            is_monitored=True,
            is_enabled=True,
        )
    )
    item = SourceItemService(db_session).ingest(
        SourceItemCreate(
            source_id=source.id,
            url="https://s.test/b",
            canonical_url="https://s.test/b",
            content_hash="s1",
            title="Nota",
            clean_text="texto",
        )
    ).item
    event = EventService(db_session).create(
        EventCreate(
            title_internal="Con tokens",
            event_type="otro",
            source_item_id=item.id,
            short_summary="resumen",
        )
    )
    db_session.add(
        LlmUsage(
            event_id=event.id,
            source_item_id=item.id,
            stage="claim_resolution",
            model_role="claim_resolution",
            provider="openai",
            model="gpt-4o-mini",
            prompt_tokens=50,
            completion_tokens=20,
            total_tokens=70,
        )
    )
    db_session.commit()

    with TestClient(app) as client:
        login = client.post("/api/v1/admin/login", json={"password": settings.admin_password})
        assert login.status_code == 200

        stats = client.get("/api/v1/admin/stats")
        assert stats.status_code == 200
        body = stats.json()
        assert body["tokens_24h"]["total_tokens"] >= 70
        assert any(row["model_role"] == "claim_resolution" for row in body["tokens_by_role_24h"])
        assert "items_by_status" in body
        assert "running_by_stage" in body

        listing = client.get("/api/v1/admin/events?limit=10")
        assert listing.status_code == 200
        found = next(row for row in listing.json() if row["id"] == str(event.id))
        assert found["tokens_total"] == 70

        detail = client.get(f"/api/v1/admin/events/{event.id}")
        assert detail.status_code == 200
        payload = detail.json()
        assert payload["token_usage"]["total_tokens"] == 70
        assert payload["token_usage"]["by_role_stage"][0]["model_role"] == "claim_resolution"

    totals = LlmUsageRepository(db_session).totals_for_event(event.id)
    assert totals["calls"] == 1
