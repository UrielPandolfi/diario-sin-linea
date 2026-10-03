"""Caché de búsquedas. La identidad es proveedor + parámetros completos. Un error no es un acierto."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import timedelta
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.clock import utc_now
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.usage_context import get_usage_context
from app.models.provider_cache import ProviderResultCache
from app.providers.base import SearchHit
from app.services.cost_service import ATTRIBUTION_SHARED
from app.services.usage_recorder import record_llm_usage

PENDING_STALE_SECONDS = 60


def search_request_hash(provider: str, parameters: dict[str, Any]) -> str:
    canonical = json.dumps(parameters, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(f"{provider}\n{canonical}".encode("utf-8")).hexdigest()


def execute_cached_search(
    *,
    provider: str,
    parameters: dict[str, Any],
    fetch: Callable[[], list[SearchHit]],
) -> list[SearchHit]:
    settings = get_settings()
    if not settings.search_cache_enabled:
        return fetch()
    digest = search_request_hash(provider, parameters)
    cached = _fresh_success(provider, digest)
    if cached is not None:
        _record_hit(provider, cached)
        return _hits_from_row(cached)
    if not _claim_pending(provider, digest, parameters):
        waited = _wait_for_peer(provider, digest)
        if waited is not None:
            _record_hit(provider, waited)
            return _hits_from_row(waited)
        if not _claim_pending(provider, digest, parameters):
            return fetch()
    try:
        hits = fetch()
    except Exception as exc:
        _finish(provider=provider, digest=digest, status="error", response=None, error=str(exc)[:500])
        raise
    _finish(
        provider=provider,
        digest=digest,
        status="success",
        response={"hits": [hit.model_dump(mode="json") for hit in hits]},
        error=None,
        ttl_seconds=int(settings.search_cache_ttl_seconds),
    )
    return hits


def _fresh_success(provider: str, digest: str) -> ProviderResultCache | None:
    session = SessionLocal()
    try:
        now = utc_now()
        row = session.scalars(
            select(ProviderResultCache)
            .where(
                ProviderResultCache.kind == "search",
                ProviderResultCache.provider == provider,
                ProviderResultCache.request_hash == digest,
                ProviderResultCache.status == "success",
                ProviderResultCache.expires_at.is_not(None),
                ProviderResultCache.expires_at > now,
            )
            .order_by(ProviderResultCache.finished_at.desc())
        ).first()
        if row is not None:
            _ = row.response_json
            session.expunge(row)
        return row
    finally:
        session.close()


def _claim_pending(provider: str, digest: str, parameters: dict[str, Any]) -> bool:
    session = SessionLocal()
    try:
        now = utc_now()
        stale = session.scalars(
            select(ProviderResultCache).where(
                ProviderResultCache.kind == "search",
                ProviderResultCache.provider == provider,
                ProviderResultCache.request_hash == digest,
                ProviderResultCache.status == "pending",
                ProviderResultCache.created_at < now - timedelta(seconds=PENDING_STALE_SECONDS),
            )
        ).first()
        if stale is not None:
            session.delete(stale)
            session.commit()
        ctx = get_usage_context()
        row = ProviderResultCache(
            kind="search",
            provider=provider,
            request_hash=digest,
            request_json=parameters,
            status="pending",
            event_id=ctx.event_id,
            pipeline_run_id=ctx.pipeline_run_id,
        )
        session.add(row)
        session.commit()
        return True
    except IntegrityError:
        session.rollback()
        return False
    finally:
        session.close()


def _wait_for_peer(provider: str, digest: str) -> ProviderResultCache | None:
    deadline = time.monotonic() + PENDING_STALE_SECONDS
    while time.monotonic() < deadline:
        row = _fresh_success(provider, digest)
        if row is not None:
            return row
        session = SessionLocal()
        try:
            pending = session.scalars(
                select(ProviderResultCache).where(
                    ProviderResultCache.kind == "search",
                    ProviderResultCache.provider == provider,
                    ProviderResultCache.request_hash == digest,
                    ProviderResultCache.status == "pending",
                )
            ).first()
        finally:
            session.close()
        if pending is None:
            return None
        time.sleep(0.05)
    return None


def _finish(
    *,
    provider: str,
    digest: str,
    status: str,
    response: dict | None,
    error: str | None,
    ttl_seconds: int | None = None,
) -> None:
    session = SessionLocal()
    try:
        row = session.scalars(
            select(ProviderResultCache).where(
                ProviderResultCache.kind == "search",
                ProviderResultCache.provider == provider,
                ProviderResultCache.request_hash == digest,
                ProviderResultCache.status == "pending",
            )
        ).first()
        if row is None:
            return
        row.status = status
        row.response_json = response
        row.error_message = error
        row.finished_at = utc_now()
        if status == "success" and ttl_seconds:
            row.expires_at = utc_now() + timedelta(seconds=ttl_seconds)
        session.commit()
    finally:
        session.close()


def _hits_from_row(row: ProviderResultCache) -> list[SearchHit]:
    payload = row.response_json or {}
    hits = payload.get("hits") if isinstance(payload, dict) else None
    if not isinstance(hits, list):
        return []
    return [SearchHit.model_validate(item) for item in hits]


def _record_hit(provider: str, row: ProviderResultCache) -> None:
    ctx = get_usage_context()
    shared = ctx.event_id is not None and row.event_id is not None and ctx.event_id != row.event_id
    record_llm_usage(
        provider=provider,
        model="search",
        call_kind="search",
        usage_reported=True,
        attribution_kind=ATTRIBUTION_SHARED if shared else None,
        request_options={
            "cache_hit": True,
            "cache_id": str(row.id),
            "request_hash": row.request_hash,
            "source_event_id": str(row.event_id) if row.event_id else None,
        },
    )
