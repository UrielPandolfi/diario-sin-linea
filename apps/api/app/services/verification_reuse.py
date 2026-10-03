"""Reutiliza una verificación ya concluida del mismo suceso. No fabrica el par con claims."""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import utc_now
from app.core.config import get_settings
from app.core.prompts import prompt_version
from app.core.source_content import body_source_from_item
from app.domain.enums import PipelineStatus
from app.models.article import Article, Correction
from app.models.event import Event
from app.models.pipeline import PipelineRun
from app.providers.registry import ModelRole, _structured_role_config
from app.schemas.editorial_evidence import CONTRACT_VERSION
from app.services.evidence_comparison import COMPARISON_POLICY_VERSION
from app.services.verification_outcome import VERIFICATION_STAGE

_PROMPTS = ("verification.md", "verification_plan.md", "claim_evidence_assessment.md")
_ROLES = (
    ModelRole.ULTRA_LIGHT_PROCESSING,
    ModelRole.VERIFICATION,
)


def verification_identity(session: Session, event: Event) -> str:
    payload = {
        "claims": _claim_rows(event),
        "sources": _source_rows(event),
        "prompts": {name: prompt_version(name) for name in _PROMPTS},
        "contract": CONTRACT_VERSION,
        "comparison_policy": COMPARISON_POLICY_VERSION,
        "models": _model_stamp(),
        "claim_run": _claim_run_stamp(session, event.id),
    }
    raw = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def reusable_verification(session: Session, event: Event) -> dict[str, Any] | None:
    settings = get_settings()
    if not settings.verification_reuse_enabled:
        return None
    identity = verification_identity(session, event)
    previous = session.scalars(
        select(PipelineRun)
        .where(
            PipelineRun.event_id == event.id,
            PipelineRun.stage == VERIFICATION_STAGE,
            PipelineRun.status == PipelineStatus.SUCCESS,
        )
        .order_by(PipelineRun.finished_at.desc())
    ).first()
    if previous is None or previous.finished_at is None:
        return None
    meta = previous.metadata_json or {}
    if meta.get("reuse_identity") != identity:
        return None
    if meta.get("error") or meta.get("search_unavailable"):
        return None
    if previous.finished_at + timedelta(seconds=int(settings.verification_reuse_ttl_seconds)) <= utc_now():
        return None
    if not _decisions_cover_selection(meta):
        return None
    if not _claim_run_still_matches(session, meta):
        return None
    if _newer_source(event, previous.finished_at):
        return None
    if _newer_correction(session, event.id, previous.finished_at):
        return None
    copied = dict(meta)
    copied["reused_from"] = str(previous.id)
    copied["reused"] = True
    return copied


def _decisions_cover_selection(meta: dict[str, Any]) -> bool:
    decisions = meta.get("decision_by_claim_id")
    if not isinstance(decisions, dict):
        return False
    selected = meta.get("selected")
    if not isinstance(selected, list):
        return False
    for row in selected:
        if not isinstance(row, dict):
            return False
        claim_id = str(row.get("claim_id") or "")
        if claim_id and claim_id not in decisions:
            return False
    return True


def _claim_run_still_matches(session: Session, meta: dict[str, Any]) -> bool:
    based_on = meta.get("based_on_claim_run_id")
    fingerprint = meta.get("claims_fingerprint")
    if not based_on or not fingerprint:
        return False
    try:
        run_id = UUID(str(based_on))
    except ValueError:
        return False
    run = session.get(PipelineRun, run_id)
    if run is None or run.status != PipelineStatus.SUCCESS:
        return False
    stored = (run.metadata_json or {}).get("claims_fingerprint")
    return stored == fingerprint


def _newer_source(event: Event, finished_at) -> bool:
    for link in event.event_sources or []:
        if link.added_at and link.added_at > finished_at:
            return True
    return False


def _newer_correction(session: Session, event_id: UUID, finished_at) -> bool:
    row = session.scalars(
        select(Correction.id)
        .join(Article, Article.id == Correction.article_id)
        .where(Article.event_id == event_id, Correction.created_at > finished_at)
        .limit(1)
    ).first()
    return row is not None


def _claim_rows(event: Event) -> list[dict[str, Any]]:
    rows = []
    for claim in sorted(event.claims or [], key=lambda item: str(item.id)):
        evidence = []
        for item in sorted(claim.evidence or [], key=lambda ev: str(ev.id)):
            source = item.source_item
            evidence.append(
                {
                    "source_item_id": str(item.source_item_id),
                    "content_hash": getattr(source, "content_hash", None) if source is not None else None,
                    "excerpt": item.excerpt,
                    "source_url": item.source_url,
                    "evidence_type": str(item.evidence_type),
                    "body_source": body_source_from_item(source) if source is not None else None,
                }
            )
        rows.append(
            {
                "id": str(claim.id),
                "canonical_text": claim.canonical_text,
                "claim_type": claim.claim_type,
                "subject": claim.subject,
                "predicate": claim.predicate,
                "object_text": claim.object_text,
                "normalized_value": claim.normalized_value,
                "unit": claim.unit,
                "occurred_at": claim.occurred_at.isoformat() if claim.occurred_at else None,
                "evidence": evidence,
            }
        )
    return rows


def _source_rows(event: Event) -> list[dict[str, str]]:
    rows = []
    for link in event.event_sources or []:
        item = link.source_item
        rows.append(
            {
                "source_item_id": str(link.source_item_id),
                "content_hash": str(getattr(item, "content_hash", "") or ""),
                "relation": str(link.relation_type),
            }
        )
    return sorted(rows, key=lambda row: row["source_item_id"])


def _model_stamp() -> dict[str, Any]:
    stamp = {}
    for role in _ROLES:
        provider, model, thinking = _structured_role_config(role)
        stamp[role.value] = {"provider": provider, "model": model, "thinking": thinking}
    return stamp


def _claim_run_stamp(session: Session, event_id: UUID) -> dict[str, Any] | None:
    from app.services.verification_outcome import latest_success_claim_resolution

    run = latest_success_claim_resolution(session, event_id)
    if run is None:
        return None
    meta = run.metadata_json or {}
    return {"id": str(run.id), "fingerprint": meta.get("claims_fingerprint")}
