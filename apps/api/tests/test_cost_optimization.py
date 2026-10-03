"""Perfil candidato, medición y reutilización. Sin llamadas pagas."""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.clock import utc_now
from app.core.config import get_settings
from app.core.usage_context import usage_scope
from app.domain.enums import ArticleStatus, IngestionMethod, PipelineStatus
from app.models import Article, Claim, Correction, LlmUsage, PipelineRun
from app.models.event import EventSource as EventSourceModel
from app.providers.base import SearchHit, SearchQuery
from app.providers.model_profile import profile_for
from app.providers.openai_provider import OpenAIStructuredProvider
from app.schemas import EventCreate, SourceCreate, SourceItemCreate
from app.services.call_budget import CallBudgetExceeded, clear_budget, install_budget
from app.services.cost_service import (
    COST_CALCULATED,
    COST_UNKNOWN,
    KIND_CACHED_READ,
    KIND_CACHED_WRITE,
    KIND_INPUT,
    KIND_OUTPUT,
    estimate_usage_cost,
    is_deepseek_peak,
)
from app.services.event_service import EventService
from app.services.search_cache import execute_cached_search, search_request_hash
from app.services.source_item_service import SourceItemService
from app.services.source_service import SourceService
from app.services.usage_recorder import attach_pipeline_run_usages, record_llm_usage
from app.services.verification_reuse import reusable_verification, verification_identity


class _Ok(BaseModel):
    ok: bool


def _rates() -> dict:
    return {
        ("deepseek", "deepseek-flash", KIND_INPUT): Decimal("0.15"),
        ("deepseek", "deepseek-flash", KIND_CACHED_READ): Decimal("0.003"),
        ("deepseek", "deepseek-flash", KIND_OUTPUT): Decimal("0.60"),
        ("openai", "gpt-5.6-luna", KIND_INPUT): Decimal("0.20"),
        ("openai", "gpt-5.6-luna", KIND_CACHED_READ): Decimal("0.02"),
        ("openai", "gpt-5.6-luna", KIND_CACHED_WRITE): Decimal("0.25"),
        ("openai", "gpt-5.6-luna", KIND_OUTPUT): Decimal("1.20"),
    }


def test_candidate_profile_is_off_by_default() -> None:
    assert profile_for("verification") == (None, None, None)


def test_candidate_profile_assigns_roles_and_disables_thinking(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "cost_profile", "candidate")
    monkeypatch.setattr(get_settings(), "cost_profile_roles", "")
    assert profile_for("verification") == ("deepseek", "deepseek-v4-pro", "disabled")
    assert profile_for("auditing") == ("deepseek", "deepseek-flash", "disabled")
    assert profile_for("light_processing") == (None, None, None)
    assert profile_for("writing") == (None, None, None)


def test_candidate_profile_can_limit_roles(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "cost_profile", "candidate")
    monkeypatch.setattr(get_settings(), "cost_profile_roles", "auditing")
    assert profile_for("auditing")[1] == "deepseek-flash"
    assert profile_for("verification") == (None, None, None)


def test_deepseek_peak_windows() -> None:
    assert is_deepseek_peak(datetime(2026, 10, 5, 2, 0, tzinfo=timezone.utc)) is True
    assert is_deepseek_peak(datetime(2026, 10, 5, 5, 0, tzinfo=timezone.utc)) is False
    assert is_deepseek_peak(datetime(2026, 10, 5, 8, 0, tzinfo=timezone.utc)) is True
    assert is_deepseek_peak(datetime(2026, 10, 4, 2, 0, tzinfo=timezone.utc)) is False


def test_flash_peak_doubles_and_unknown_is_not_zero() -> None:
    off = estimate_usage_cost(
        provider="deepseek",
        model_requested="deepseek-flash",
        model_reported="deepseek-flash",
        prompt_tokens=1_000_000,
        completion_tokens=0,
        total_tokens=1_000_000,
        cache_read_tokens=0,
        cache_write_tokens=0,
        usage_reported=True,
        rates=_rates(),
        book_id=None,
        at=datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc),
    )
    peak = estimate_usage_cost(
        provider="deepseek",
        model_requested="deepseek-flash",
        model_reported="deepseek-flash",
        prompt_tokens=1_000_000,
        completion_tokens=0,
        total_tokens=1_000_000,
        cache_read_tokens=0,
        cache_write_tokens=0,
        usage_reported=True,
        rates=_rates(),
        book_id=None,
        at=datetime(2026, 10, 5, 2, 0, tzinfo=timezone.utc),
    )
    assert off.usd == Decimal("0.1500000000")
    assert peak.usd == Decimal("0.3000000000")
    unknown = estimate_usage_cost(
        provider="deepseek",
        model_requested="deepseek-chat",
        model_reported=None,
        prompt_tokens=10,
        completion_tokens=1,
        total_tokens=11,
        cache_read_tokens=0,
        cache_write_tokens=0,
        usage_reported=True,
        rates=_rates(),
        book_id=None,
    )
    assert unknown.status == COST_UNKNOWN
    assert unknown.usd is None


def test_luna_cache_write_is_not_also_billed_as_input() -> None:
    estimate = estimate_usage_cost(
        provider="openai",
        model_requested="gpt-5.6-luna",
        model_reported="gpt-5.6-luna",
        prompt_tokens=100,
        completion_tokens=0,
        total_tokens=100,
        cache_read_tokens=0,
        cache_write_tokens=100,
        usage_reported=True,
        rates=_rates(),
        book_id=None,
    )
    assert estimate.status == COST_CALCULATED
    assert estimate.snapshot["uncached_prompt_tokens"] == 0
    assert estimate.usd == Decimal("0.0000250000")


def test_deepseek_request_disables_thinking_explicitly(db_session: Session) -> None:
    captured: dict = {}

    class _Completions:
        def create(self, **kwargs):
            captured.update(kwargs)
            message = SimpleNamespace(content='{"ok": true}', reasoning_content=None)
            usage = SimpleNamespace(
                prompt_tokens=8,
                completion_tokens=2,
                total_tokens=10,
                completion_tokens_details=SimpleNamespace(reasoning_tokens=0),
            )
            return SimpleNamespace(
                model="deepseek-flash",
                choices=[SimpleNamespace(message=message)],
                usage=usage,
            )

    client = SimpleNamespace(chat=SimpleNamespace(completions=_Completions()))
    provider = OpenAIStructuredProvider(
        api_key="test",
        model="deepseek-flash",
        provider_name="deepseek",
        client=client,
        thinking="disabled",
    )
    parsed = provider.generate_structured(system_prompt="s", user_prompt="u", schema=_Ok)
    assert parsed.ok is True
    assert captured["extra_body"] == {"thinking": {"type": "disabled"}}
    assert captured["model"] == "deepseek-flash"
    row = db_session.scalars(select(LlmUsage).where(LlmUsage.model_requested == "deepseek-flash")).first()
    db_session.expire_all()
    row = db_session.scalars(select(LlmUsage).where(LlmUsage.model_requested == "deepseek-flash")).first()
    assert row is not None
    assert row.model_reported == "deepseek-flash"
    assert row.request_options["thinking"] == {"type": "disabled"}
    assert row.request_options["reasoning_content_present"] is False


def test_budget_blocks_before_the_provider_call(db_session: Session) -> None:
    called = {"n": 0}

    class _Completions:
        def create(self, **kwargs):
            called["n"] += 1
            raise AssertionError("no debía llamar")

    client = SimpleNamespace(chat=SimpleNamespace(completions=_Completions()))
    provider = OpenAIStructuredProvider(
        api_key="test",
        model="deepseek-v4-pro",
        provider_name="deepseek",
        client=client,
        thinking="disabled",
    )
    install_budget(Decimal("0.0000001"))
    try:
        with pytest.raises(CallBudgetExceeded):
            provider.generate_structured(system_prompt="s" * 4000, user_prompt="u" * 4000, schema=_Ok)
    finally:
        clear_budget()
    assert called["n"] == 0


def test_search_hash_includes_full_parameters() -> None:
    left = search_request_hash("exa", {"query": "a", "numResults": 3, "type": "auto"})
    right = search_request_hash("exa", {"query": "a", "numResults": 4, "type": "auto"})
    assert left != right


def test_search_cache_reuses_only_fresh_success(monkeypatch, db_session: Session) -> None:
    monkeypatch.setattr(get_settings(), "search_cache_enabled", True)
    monkeypatch.setattr(get_settings(), "search_cache_ttl_seconds", 7200)
    calls = {"n": 0}

    def fetch():
        calls["n"] += 1
        return [SearchHit(title="t", url="https://ejemplo.test/a", snippet="s")]

    params = {"query": "mismo", "numResults": 2, "type": "auto", "contents": {"highlights": True}}
    first = execute_cached_search(provider="exa", parameters=params, fetch=fetch)
    second = execute_cached_search(provider="exa", parameters=params, fetch=fetch)
    assert calls["n"] == 1
    assert first[0].url == second[0].url
    other = dict(params)
    other["numResults"] = 9
    execute_cached_search(provider="exa", parameters=other, fetch=fetch)
    assert calls["n"] == 2

    def boom():
        calls["n"] += 1
        raise RuntimeError("fallo técnico")

    with pytest.raises(RuntimeError):
        execute_cached_search(provider="exa", parameters={"query": "falla"}, fetch=boom)
    with pytest.raises(RuntimeError):
        execute_cached_search(provider="exa", parameters={"query": "falla"}, fetch=boom)
    assert calls["n"] == 4


def test_search_cache_single_flight(monkeypatch, db_session: Session) -> None:
    monkeypatch.setattr(get_settings(), "search_cache_enabled", True)
    monkeypatch.setattr(get_settings(), "search_cache_ttl_seconds", 7200)
    calls = {"n": 0}
    lock = threading.Lock()
    started = threading.Event()

    def fetch():
        with lock:
            calls["n"] += 1
        started.set()
        threading.Event().wait(0.2)
        return [SearchHit(title="t", url="https://ejemplo.test/b", snippet=None)]

    params = {"query": "concurrente", "numResults": 1}
    results: list[list[SearchHit]] = []

    def run():
        results.append(execute_cached_search(provider="exa", parameters=params, fetch=fetch))

    threads = [threading.Thread(target=run, daemon=True), threading.Thread(target=run, daemon=True)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)
    assert calls["n"] == 1
    assert len(results) == 2


def _event(db_session: Session):
    source = SourceService(db_session).create(
        SourceCreate(
            name="Costo",
            preferred_ingestion_method=IngestionMethod.RSS,
            feed_url="https://costo.test/rss",
            is_monitored=True,
            is_enabled=True,
        )
    )
    item = SourceItemService(db_session).ingest(
        SourceItemCreate(
            source_id=source.id,
            url="https://costo.test/a",
            canonical_url="https://costo.test/a",
            content_hash="costo-a",
            title="T",
            clean_text="cuerpo",
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
    claim = Claim(
        event_id=event.id,
        canonical_text="hubo un choque",
        claim_type="hecho",
        subject="auto",
        predicate="chocó",
        object_text="colectivo",
    )
    db_session.add(claim)
    db_session.commit()
    db_session.refresh(event)
    return event, claim


def test_uncommitted_run_keeps_event_id(db_session: Session) -> None:
    event, _claim = _event(db_session)
    missing_run = uuid4()
    with usage_scope(stage="verification", event_id=event.id, pipeline_run_id=missing_run):
        record_llm_usage(
            provider="openai",
            model="gpt-4o",
            prompt_tokens=10,
            completion_tokens=2,
            total_tokens=12,
        )
    row = db_session.scalars(select(LlmUsage).where(LlmUsage.event_id == event.id)).one()
    assert row.pipeline_run_id is None
    assert row.request_options["intended_pipeline_run_id"] == str(missing_run)
    run = PipelineRun(event_id=event.id, stage="verification", status=PipelineStatus.RUNNING)
    db_session.add(run)
    db_session.flush()
    row.request_options = {**(row.request_options or {}), "intended_pipeline_run_id": str(run.id)}
    db_session.flush()
    attach_pipeline_run_usages(db_session, run.id)
    db_session.commit()
    db_session.refresh(row)
    assert row.pipeline_run_id == run.id
    assert row.event_id == event.id


def test_verification_reuse_requires_identity_ttl_and_real_pairing(db_session: Session, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "verification_reuse_enabled", True)
    monkeypatch.setattr(get_settings(), "verification_reuse_ttl_seconds", 21600)
    event, claim = _event(db_session)
    claim_run = PipelineRun(
        event_id=event.id,
        stage="claim_resolution",
        status=PipelineStatus.SUCCESS,
        finished_at=utc_now(),
        metadata_json={"claims_fingerprint": "fp-1"},
    )
    db_session.add(claim_run)
    db_session.commit()
    db_session.refresh(event)
    identity = verification_identity(db_session, event)
    verify = PipelineRun(
        event_id=event.id,
        stage="verification",
        status=PipelineStatus.SUCCESS,
        finished_at=utc_now(),
        metadata_json={
            "reuse_identity": identity,
            "claims_fingerprint": "fp-1",
            "based_on_claim_run_id": str(claim_run.id),
            "selected": [{"claim_id": str(claim.id)}],
            "decision_by_claim_id": {str(claim.id): {"label": "attributed"}},
            "search_unavailable": False,
        },
    )
    db_session.add(verify)
    db_session.commit()
    reused = reusable_verification(db_session, event)
    assert reused is not None
    assert reused["reused_from"] == str(verify.id)
    assert reused["based_on_claim_run_id"] == str(claim_run.id)

    verify.finished_at = utc_now() - timedelta(hours=7)
    db_session.commit()
    assert reusable_verification(db_session, event) is None

    verify.finished_at = utc_now()
    claim.subject = "otro sujeto"
    db_session.commit()
    db_session.refresh(event)
    assert reusable_verification(db_session, event) is None

    claim.subject = "auto"
    db_session.commit()
    db_session.refresh(event)
    article = Article(
        event_id=event.id,
        slug=f"costo-{uuid4().hex[:8]}",
        headline="h",
        summary="s",
        body="b",
        status=ArticleStatus.PUBLISHED,
        published_version=2,
        current_version=3,
    )
    db_session.add(article)
    db_session.flush()
    published_before = article.published_version
    db_session.add(Correction(article_id=article.id, description="dato corregido"))
    db_session.commit()
    assert reusable_verification(db_session, event) is None
    db_session.refresh(article)
    assert article.published_version == published_before

    db_session.execute(delete(Correction))
    link = db_session.scalars(select(EventSourceModel).where(EventSourceModel.event_id == event.id)).one()
    verify.finished_at = utc_now() - timedelta(minutes=5)
    link.added_at = utc_now()
    db_session.commit()
    db_session.refresh(event)
    assert reusable_verification(db_session, event) is None


def test_failed_search_is_not_a_valid_result(monkeypatch, db_session: Session) -> None:
    monkeypatch.setattr(get_settings(), "search_cache_enabled", True)
    calls = {"n": 0}

    def fetch():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("timeout")
        return [SearchHit(title="ok", url="https://ejemplo.test/c", snippet=None)]

    params = {"query": SearchQuery(text="q", count=1).text, "count": 1, "freshness": "pd"}
    with pytest.raises(RuntimeError):
        execute_cached_search(provider="brave", parameters=params, fetch=fetch)
    hits = execute_cached_search(provider="brave", parameters=params, fetch=fetch)
    assert hits[0].url == "https://ejemplo.test/c"
    assert calls["n"] == 2
