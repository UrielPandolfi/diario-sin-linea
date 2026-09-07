from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import ClaimStatus, PipelineStatus
from app.models import Claim, PipelineRun

VERIFICATION_STAGE = "verification"

_STRONG_STATUSES = {ClaimStatus.SUPPORTED.value, ClaimStatus.DISPROVEN.value}


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


@dataclass
class VerificationView:
    selected_ids: set[str] = field(default_factory=set)
    skipped_search: set[str] = field(default_factory=set)
    primary_source_supports: dict[str, bool] = field(default_factory=dict)
    sol_by_id: dict[str, dict[str, Any]] = field(default_factory=dict)
    finished_at: datetime | None = None


def latest_success_verification(session: Session, event_id: UUID) -> PipelineRun | None:
    return session.scalars(
        select(PipelineRun)
        .where(
            PipelineRun.event_id == event_id,
            PipelineRun.stage == VERIFICATION_STAGE,
            PipelineRun.status == PipelineStatus.SUCCESS,
        )
        .order_by(PipelineRun.finished_at.desc())
    ).first()


def view_from_mapping(payload: dict[str, Any] | None, *, finished_at: datetime | None = None) -> VerificationView:
    raw = payload or {}
    selected: set[str] = set()
    for row in raw.get("selected") or []:
        if isinstance(row, dict) and row.get("claim_id"):
            selected.add(str(row["claim_id"]))
        elif isinstance(row, str):
            selected.add(row)
    skipped = {str(item) for item in (raw.get("skipped_search") or [])}
    primary_raw = raw.get("primary_source_supports_claim") or {}
    primary = {str(key): bool(value) for key, value in primary_raw.items()} if isinstance(primary_raw, dict) else {}
    sol_by_id: dict[str, dict[str, Any]] = {}
    for row in raw.get("sol") or []:
        if not isinstance(row, dict) or not row.get("claim_id"):
            continue
        sol_by_id[str(row["claim_id"])] = row
    return VerificationView(
        selected_ids=selected,
        skipped_search=skipped,
        primary_source_supports=primary,
        sol_by_id=sol_by_id,
        finished_at=_aware(finished_at),
    )


def parse_verification_run(run: PipelineRun | None) -> VerificationView:
    if run is None or run.status != PipelineStatus.SUCCESS:
        return VerificationView()
    return view_from_mapping(run.metadata_json, finished_at=run.finished_at)


def is_strong_verification(claim_id: UUID | str, view: VerificationView) -> bool:
    cid = str(claim_id)
    if cid not in view.selected_ids:
        return False
    if cid in view.skipped_search:
        return False
    sol = view.sol_by_id.get(cid)
    if not sol:
        return False
    if sol.get("unresolved") is True:
        return False
    status_after = str(sol.get("status_after") or "")
    if status_after not in _STRONG_STATUSES:
        return False
    if status_after == ClaimStatus.SUPPORTED.value and not view.primary_source_supports.get(cid):
        return False
    return True


def has_new_material_evidence(claim: Claim, siblings: list[Claim], run: PipelineRun | None) -> bool:
    cutoff = _aware(getattr(run, "finished_at", None))
    if cutoff is None:
        return False
    for member in siblings:
        created = _aware(getattr(member, "created_at", None))
        if member.id != claim.id and created is not None and created > cutoff:
            return True
        for row in getattr(member, "evidence", None) or []:
            row_created = _aware(getattr(row, "created_at", None))
            if row_created is not None and row_created > cutoff:
                return True
    return False


def is_verification_locked(
    claim: Claim,
    siblings: list[Claim],
    view: VerificationView,
    run: PipelineRun | None,
) -> bool:
    if not is_strong_verification(claim.id, view):
        return False
    return not has_new_material_evidence(claim, siblings, run)
