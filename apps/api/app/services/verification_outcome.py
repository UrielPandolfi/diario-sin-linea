from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import ClaimStatus, PipelineStatus
from app.models import Claim, PipelineRun
from app.schemas.editorial_evidence import (
    CONTRACT_VERSION,
    StatementEvidenceClass,
    evaluation_is_complete,
    read_evaluation_state,
    decision_looks_like_skip,
)

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


def _run_status(run: PipelineRun) -> str:
    status = run.status
    return str(status.value if hasattr(status, "value") else status)


def _is_success(run: PipelineRun) -> bool:
    return _run_status(run) == PipelineStatus.SUCCESS.value


def _verification_for_claim(claim_run: PipelineRun, runs: Sequence[PipelineRun]) -> PipelineRun | None:
    """Match a SUCCESS verification to the claim set, not only to the newest run id.

    A later claim_resolution can keep the same claims_fingerprint (source_already_extracted).
    Requiring based_on_claim_run_id == newest run id drops a still-valid verification.
    A different fingerprint is a new claim set and must not reuse the prior approval.
    """
    fingerprint = (claim_run.metadata_json or {}).get("claims_fingerprint")
    if not fingerprint:
        return None
    claim_id = str(claim_run.id)
    same_fingerprint: PipelineRun | None = None
    for run in runs:
        if run.stage != VERIFICATION_STAGE or not _is_success(run):
            continue
        meta = run.metadata_json or {}
        if meta.get("claims_fingerprint") != fingerprint:
            continue
        if str(meta.get("based_on_claim_run_id") or "") == claim_id:
            return run
        if same_fingerprint is None:
            same_fingerprint = run
    return same_fingerprint


def pair_from_runs(runs: list[PipelineRun]) -> tuple[PipelineRun | None, PipelineRun | None]:
    claim_run = None
    for run in runs:
        if run.stage == CLAIM_STAGE and _is_success(run):
            claim_run = run
            break
    if claim_run is None:
        return None, None
    verify_run = _verification_for_claim(claim_run, runs)
    if verify_run is None:
        return claim_run, None
    based_on = str((verify_run.metadata_json or {}).get("based_on_claim_run_id") or "")
    if based_on:
        for run in runs:
            if run.stage == CLAIM_STAGE and _is_success(run) and str(run.id) == based_on:
                return run, verify_run
    return claim_run, verify_run


def compatible_verification_pair(session: Session, event_id: UUID) -> tuple[PipelineRun | None, PipelineRun | None]:
    claim_run = latest_success_claim_resolution(session, event_id)
    if claim_run is None:
        return None, None
    verify_runs = list(
        session.scalars(
            select(PipelineRun)
            .where(
                PipelineRun.event_id == event_id,
                PipelineRun.stage == VERIFICATION_STAGE,
                PipelineRun.status == PipelineStatus.SUCCESS,
            )
            .order_by(PipelineRun.finished_at.desc())
        ).all()
    )
    verify_run = _verification_for_claim(claim_run, verify_runs)
    if verify_run is None:
        return claim_run, None
    based_on = str((verify_run.metadata_json or {}).get("based_on_claim_run_id") or "")
    if based_on:
        try:
            based = session.get(PipelineRun, UUID(based_on))
        except (TypeError, ValueError):
            based = None
        if based is not None and based.stage == CLAIM_STAGE and _is_success(based):
            return based, verify_run
    return claim_run, verify_run


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


def view_from_evidence_snapshot(snapshot: dict[str, Any] | None) -> VerificationView:
    """VerificationView bound to a version snapshot. Never falls back to live verify."""
    if not snapshot:
        return VerificationView()
    context = snapshot.get("article_context") if isinstance(snapshot.get("article_context"), dict) else {}
    verification = context.get("verification") if isinstance(context.get("verification"), dict) else {}
    decisions_raw = snapshot.get("decision_by_claim_id")
    if not isinstance(decisions_raw, dict) or not decisions_raw:
        decisions_raw = verification.get("decision_by_claim_id") if isinstance(verification.get("decision_by_claim_id"), dict) else {}
    decisions = {str(key): value for key, value in decisions_raw.items() if isinstance(value, dict)}

    selected: set[str] = set()
    for row in verification.get("selected") or []:
        if isinstance(row, dict) and row.get("claim_id"):
            selected.add(str(row["claim_id"]))
        elif isinstance(row, str):
            selected.add(row)
    if not selected:
        for row in snapshot.get("evaluated_claims") or []:
            if isinstance(row, dict) and row.get("claim_id"):
                selected.add(str(row["claim_id"]))
    if not selected:
        for cid, decision in decisions.items():
            if evaluation_is_complete(decision):
                selected.add(cid)
            elif read_evaluation_state(decision) is None and not decision_looks_like_skip(decision):
                selected.add(cid)

    skipped_search = {
        cid
        for cid, decision in decisions.items()
        if str(decision.get("llm_reason") or "") == "skipped_search"
    }
    primary = {
        cid: True
        for cid, decision in decisions.items()
        if isinstance(decision.get("support_basis"), dict)
        and decision["support_basis"].get("primary_access") == "found_relevant"
    }
    sol_by_id: dict[str, dict[str, Any]] = {}
    for row in verification.get("sol") or []:
        if not isinstance(row, dict) or not row.get("claim_id"):
            continue
        sol_by_id[str(row["claim_id"])] = row
    stale = bool(snapshot.get("stale_verification") or verification.get("stale_verification"))
    fingerprint = snapshot.get("claims_fingerprint") or verification.get("claims_fingerprint")
    based_on = snapshot.get("based_on_claim_run_id") or verification.get("based_on_claim_run_id")
    # Pairing is snapshot-local (same rule as parse_verification_run). Do not
    # require verification_run_id: legacy writing snapshots may omit it and
    # still carry fingerprint + based_on for evaluated copy.
    paired = bool(fingerprint and based_on) and not stale
    return VerificationView(
        selected_ids=selected,
        skipped_search=skipped_search,
        primary_source_supports=primary,
        sol_by_id=sol_by_id,
        decision_by_claim_id=decisions,
        claims_fingerprint=str(fingerprint) if fingerprint else None,
        based_on_claim_run_id=str(based_on) if based_on else None,
        paired=paired,
    )


def is_strong_verification(claim_id: UUID | str, view: VerificationView, *, claim: Any = None) -> bool:
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
        if (
            status_after == ClaimStatus.SUPPORTED.value
            and basis.get("statement_evidence_class") == StatementEvidenceClass.AUTHENTIC_PRIMARY.value
        ):
            return True
        return _independent_reporting_is_checked(claim, basis, status_after)
    if status_after == ClaimStatus.SUPPORTED.value and view.primary_source_supports.get(cid):
        return True
    if status_after == ClaimStatus.SUPPORTED.value:
        if basis.get("statement_evidence_class") == StatementEvidenceClass.AUTHENTIC_PRIMARY.value:
            return True
        if basis.get("primary_access") == "found_relevant":
            return True
        if basis.get("kind") == "primary_source":
            return True
        return _independent_reporting_is_checked(claim, basis, status_after)
    return True


def _independent_reporting_is_checked(claim: Any, basis: dict[str, Any], status_after: str) -> bool:
    if status_after != ClaimStatus.SUPPORTED.value:
        return False
    kind = basis.get("kind")
    known = int(basis.get("known_independent_count") or 0)
    if kind != "independent_reporting" and not (kind is None and known >= 2):
        return False
    if claim is None:
        return False
    from app.services.verification_policy import looks_sensitive_accusation, requires_authoritative_source

    if requires_authoritative_source(claim) or looks_sensitive_accusation(claim):
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
    if not is_strong_verification(claim.id, view, claim=claim):
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
    coverage = verify_meta.get("coverage") or claim_meta.get("coverage")
    budget = verify_meta.get("verification_budget") if isinstance(verify_meta.get("verification_budget"), dict) else {}
    central_unverified = list(budget.get("central_unverified") or []) if budget else []
    incomplete = bool(
        verify_meta.get("verification_incomplete")
        or (isinstance(coverage, dict) and coverage.get("verification_incomplete"))
        or central_unverified
    )
    based_on = verify_meta.get("based_on_claim_run_id")
    coverage_run_id = based_on or (str(claim_run.id) if claim_run is not None else None)
    return {
        "contract_version": CONTRACT_VERSION,
        "coverage_run_id": coverage_run_id,
        "verification_run_id": str(verify_run.id) if verify_run is not None else None,
        "based_on_claim_run_id": based_on,
        "claims_fingerprint": fingerprint,
        "evaluated_claims": verify_meta.get("evaluated_claims") or [],
        "decision_by_claim_id": verify_meta.get("decision_by_claim_id") or {},
        "coverage": coverage,
        "verification_budget": budget or None,
        "verification_incomplete": incomplete,
        "central_unverified": central_unverified,
        "stale_verification": verify_run is None and bool(claim_meta.get("claims_fingerprint")),
        "version": version,
    }
