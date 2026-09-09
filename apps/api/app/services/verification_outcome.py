from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import ClaimStatus, PipelineStatus
from app.models import Claim, PipelineRun
from app.schemas.editorial_evidence import CONTRACT_VERSION, StatementEvidenceClass

CLAIM_STAGE = "claim_resolution"
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
    decision_by_claim_id: dict[str, dict[str, Any]] = field(default_factory=dict)
    claims_fingerprint: str | None = None
    based_on_claim_run_id: str | None = None
    paired: bool = False
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


def latest_success_claim_resolution(session: Session, event_id: UUID) -> PipelineRun | None:
    return session.scalars(
        select(PipelineRun)
        .where(
            PipelineRun.event_id == event_id,
            PipelineRun.stage == CLAIM_STAGE,
            PipelineRun.status == PipelineStatus.SUCCESS,
        )
        .order_by(PipelineRun.finished_at.desc(), PipelineRun.started_at.desc())
    ).first()


def pair_from_runs(runs: list[PipelineRun]) -> tuple[PipelineRun | None, PipelineRun | None]:
    claim_run = None
    for run in runs:
        if run.stage == CLAIM_STAGE and run.status == PipelineStatus.SUCCESS:
            claim_run = run
            break
    if claim_run is None:
        return None, None
    fingerprint = (claim_run.metadata_json or {}).get("claims_fingerprint")
    if not fingerprint:
        return claim_run, None
    claim_id = str(claim_run.id)
    for run in runs:
        if run.stage != VERIFICATION_STAGE or run.status != PipelineStatus.SUCCESS:
            continue
        meta = run.metadata_json or {}
        if str(meta.get("based_on_claim_run_id") or "") != claim_id:
            continue
        if meta.get("claims_fingerprint") != fingerprint:
            continue
        return claim_run, run
    return claim_run, None


def compatible_verification_pair(session: Session, event_id: UUID) -> tuple[PipelineRun | None, PipelineRun | None]:
    claim_run = latest_success_claim_resolution(session, event_id)
    if claim_run is None:
        return None, None
    fingerprint = (claim_run.metadata_json or {}).get("claims_fingerprint")
    if not fingerprint:
        return claim_run, None
    verify_runs = session.scalars(
        select(PipelineRun)
        .where(
            PipelineRun.event_id == event_id,
            PipelineRun.stage == VERIFICATION_STAGE,
            PipelineRun.status == PipelineStatus.SUCCESS,
        )
        .order_by(PipelineRun.finished_at.desc())
    ).all()
    claim_id = str(claim_run.id)
    for run in verify_runs:
        meta = run.metadata_json or {}
        if str(meta.get("based_on_claim_run_id") or "") != claim_id:
            continue
        if meta.get("claims_fingerprint") != fingerprint:
            continue
        return claim_run, run
    return claim_run, None


def verification_view_for_event(session: Session, event_id: UUID) -> tuple[PipelineRun | None, VerificationView]:
    _claim_run, verify_run = compatible_verification_pair(session, event_id)
    return verify_run, parse_verification_run(verify_run, paired=verify_run is not None)


def view_from_mapping(
    payload: dict[str, Any] | None,
    *,
    finished_at: datetime | None = None,
    paired: bool = False,
) -> VerificationView:
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
    decisions_raw = raw.get("decision_by_claim_id") or {}
    decisions = {str(key): value for key, value in decisions_raw.items()} if isinstance(decisions_raw, dict) else {}
    fingerprint = raw.get("claims_fingerprint")
    based_on = raw.get("based_on_claim_run_id")
    is_paired = paired or bool(fingerprint and based_on)
    return VerificationView(
        selected_ids=selected,
        skipped_search=skipped,
        primary_source_supports=primary,
        sol_by_id=sol_by_id,
        decision_by_claim_id=decisions,
        claims_fingerprint=str(fingerprint) if fingerprint else None,
        based_on_claim_run_id=str(based_on) if based_on else None,
        paired=is_paired,
        finished_at=_aware(finished_at),
    )


def parse_verification_run(run: PipelineRun | None, *, paired: bool = False) -> VerificationView:
    if run is None or run.status != PipelineStatus.SUCCESS:
        return VerificationView()
    meta = run.metadata_json or {}
    has_pair = bool(meta.get("claims_fingerprint") and meta.get("based_on_claim_run_id"))
    return view_from_mapping(meta, finished_at=run.finished_at, paired=paired or has_pair)


def is_strong_verification(claim_id: UUID | str, view: VerificationView) -> bool:
    cid = str(claim_id)
    if cid not in view.selected_ids:
        return False
    if cid in view.skipped_search:
        return False
    decision = view.decision_by_claim_id.get(cid) or {}
    sol = view.sol_by_id.get(cid) or {}
    if decision.get("unresolved") is True or sol.get("unresolved") is True:
        return False
    status_after = str(decision.get("status") or sol.get("status_after") or "")
    if status_after not in _STRONG_STATUSES:
        return False
    role = decision.get("proposition_role")
    basis = decision.get("support_basis") or {}
    if role == "utterance":
        return (
            status_after == ClaimStatus.SUPPORTED.value
            and basis.get("statement_evidence_class") == StatementEvidenceClass.AUTHENTIC_PRIMARY.value
        )
    if status_after == ClaimStatus.SUPPORTED.value and not view.primary_source_supports.get(cid):
        if basis.get("statement_evidence_class") == StatementEvidenceClass.AUTHENTIC_PRIMARY.value:
            return True
        if basis.get("primary_access") == "found_relevant":
            return True
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
    if run is None or not view.paired:
        return False
    if not is_strong_verification(claim.id, view):
        return False
    return not has_new_material_evidence(claim, siblings, run)


def writing_evidence_snapshot(
    claim_run: PipelineRun | None,
    verify_run: PipelineRun | None,
    *,
    version: int | None,
) -> dict[str, Any]:
    claim_meta = (claim_run.metadata_json if claim_run is not None else None) or {}
    verify_meta = (verify_run.metadata_json if verify_run is not None else None) or {}
    fingerprint = verify_meta.get("claims_fingerprint") or claim_meta.get("claims_fingerprint")
    return {
        "contract_version": CONTRACT_VERSION,
        "coverage_run_id": str(claim_run.id) if claim_run is not None else None,
        "verification_run_id": str(verify_run.id) if verify_run is not None else None,
        "claims_fingerprint": fingerprint,
        "evaluated_claims": verify_meta.get("evaluated_claims") or [],
        "decision_by_claim_id": verify_meta.get("decision_by_claim_id") or {},
        "coverage": verify_meta.get("coverage") or claim_meta.get("coverage"),
        "stale_verification": verify_run is None and bool(claim_meta.get("claims_fingerprint")),
        "version": version,
    }
