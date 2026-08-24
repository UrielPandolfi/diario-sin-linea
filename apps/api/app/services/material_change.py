from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.domain.enums import ClaimImportance, ClaimStatus
from app.models import Claim

_RESOLVED = {
    ClaimStatus.SUPPORTED,
    ClaimStatus.SINGLE_SOURCE,
    ClaimStatus.DISPROVEN,
    ClaimStatus.OUTDATED,
}
_CONFIRMATION_FROM = {ClaimStatus.UNCERTAIN, ClaimStatus.SINGLE_SOURCE}
_CORRECTION_TO = {ClaimStatus.DISPROVEN, ClaimStatus.OUTDATED}


def _enum_value(value: object) -> str:
    return value.value if hasattr(value, "value") else str(value)


def snapshot_claims(claims: Sequence[Claim]) -> list[dict]:
    rows: list[dict] = []
    for claim in sorted(claims, key=lambda row: str(row.id)):
        rows.append(
            {
                "id": str(claim.id),
                "canonical_text": claim.canonical_text,
                "status": _enum_value(claim.status),
                "importance": _enum_value(claim.importance),
                "normalized_value": claim.normalized_value,
                "claim_type": claim.claim_type,
            }
        )
    return rows


def _status(value: str | ClaimStatus) -> ClaimStatus:
    if isinstance(value, ClaimStatus):
        return value
    return ClaimStatus(value)


def _importance(value: str | ClaimImportance) -> ClaimImportance:
    if isinstance(value, ClaimImportance):
        return value
    return ClaimImportance(value)


@dataclass(frozen=True)
class MaterialChange:
    is_material: bool
    reasons: list[str]


def detect_material_change(
    previous: Sequence[dict] | None,
    current: Sequence[dict],
) -> MaterialChange:
    if not previous:
        return MaterialChange(is_material=True, reasons=["first_write"])

    prev_by_id = {str(row["id"]): row for row in previous}
    curr_by_id = {str(row["id"]): row for row in current}
    reasons: list[str] = []

    for claim_id, row in curr_by_id.items():
        if claim_id not in prev_by_id:
            importance = _importance(row.get("importance") or ClaimImportance.MEDIUM)
            if importance == ClaimImportance.HIGH:
                reasons.append("new_high_claim")
            elif importance == ClaimImportance.MEDIUM:
                reasons.append("new_medium_claim")
            continue
        before = prev_by_id[claim_id]
        before_status = _status(before["status"])
        after_status = _status(row["status"])
        if before_status == ClaimStatus.CONFLICTING and after_status in _RESOLVED:
            reasons.append("conflict_resolved")
        elif before_status in _CONFIRMATION_FROM and after_status == ClaimStatus.SUPPORTED:
            reasons.append("status_confirmed")
        if after_status == ClaimStatus.CONFLICTING and before_status != ClaimStatus.CONFLICTING:
            reasons.append("status_conflict")
        if after_status in _CORRECTION_TO and before_status not in _CORRECTION_TO:
            reasons.append("status_correction")
        if (before.get("normalized_value") or None) != (row.get("normalized_value") or None):
            reasons.append("value_changed")

    for claim_id, before in prev_by_id.items():
        if claim_id in curr_by_id:
            continue
        if _importance(before.get("importance") or ClaimImportance.MEDIUM) == ClaimImportance.HIGH:
            reasons.append("claim_removed_high")

    # Preserve order, drop duplicates.
    unique: list[str] = []
    seen: set[str] = set()
    for reason in reasons:
        if reason in seen:
            continue
        seen.add(reason)
        unique.append(reason)
    return MaterialChange(is_material=bool(unique), reasons=unique)
