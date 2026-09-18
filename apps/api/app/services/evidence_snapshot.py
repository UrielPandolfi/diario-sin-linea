from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from app.domain.enums import PipelineStatus
from app.models import PipelineRun
from app.schemas.writing import ArticleContext
from app.services.pipeline_lock import AUDITING_STAGE, WRITING_STAGE
from app.services.verification_outcome import writing_evidence_snapshot

_SNAPSHOT_KEYS = (
    "contract_version",
    "coverage_run_id",
    "verification_run_id",
    "based_on_claim_run_id",
    "claims_fingerprint",
    "evaluated_claims",
    "decision_by_claim_id",
    "coverage",
    "verification_budget",
    "verification_incomplete",
    "central_unverified",
    "stale_verification",
    "version",
    "article_context",
)


def capture_evidence_snapshot(
    article_context: ArticleContext,
    claim_run: PipelineRun | None,
    verify_run: PipelineRun | None,
    *,
    version: int | None = None,
) -> dict[str, Any]:
    snap = writing_evidence_snapshot(claim_run, verify_run, version=version)
    snap["article_context"] = json.loads(article_context.model_dump_json())
    return snap


def bind_snapshot_to_version(snapshot: dict[str, Any], version: int) -> dict[str, Any]:
    bound = dict(snapshot)
    bound["version"] = int(version)
    return bound


def snapshot_from_run_metadata(meta: dict[str, Any] | None) -> dict[str, Any] | None:
    raw = meta or {}
    nested = raw.get("evidence_snapshot")
    if isinstance(nested, dict) and _looks_like_snapshot(nested):
        return dict(nested)
    if _looks_like_snapshot(raw):
        return {key: raw.get(key) for key in _SNAPSHOT_KEYS if key in raw}
    return None


def _looks_like_snapshot(payload: dict[str, Any]) -> bool:
    if payload.get("article_context"):
        return True
    return bool(payload.get("contract_version") and (payload.get("coverage") is not None or payload.get("claims_fingerprint")))


def evidence_snapshot_for_version(
    runs: Sequence[PipelineRun],
    version: int,
) -> dict[str, Any] | None:
    target = int(version)
    for run in runs:
        meta = run.metadata_json or {}
        if run.stage == AUDITING_STAGE and run.status in {PipelineStatus.SUCCESS, PipelineStatus.FAILED}:
            snap = meta.get("evidence_snapshot")
            version_after = meta.get("version_after")
            if isinstance(snap, dict) and version_after is not None and int(version_after) == target:
                return dict(snap)
        if run.stage == WRITING_STAGE and run.status == PipelineStatus.SUCCESS:
            snap = snapshot_from_run_metadata(meta)
            if snap is None:
                continue
            bound = snap.get("version") if snap.get("version") is not None else meta.get("version")
            if bound is not None and int(bound) == target:
                return snap
    return None


def article_context_from_snapshot(snapshot: dict[str, Any] | None) -> ArticleContext | None:
    if not snapshot:
        return None
    raw = snapshot.get("article_context")
    if not isinstance(raw, dict):
        return None
    try:
        return ArticleContext.model_validate(raw)
    except Exception:
        return None


def persist_snapshot_fields(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Flatten for writing-run metadata (tests read top-level keys) plus nested copy."""
    payload = {key: snapshot.get(key) for key in _SNAPSHOT_KEYS}
    payload["evidence_snapshot"] = dict(snapshot)
    return payload
