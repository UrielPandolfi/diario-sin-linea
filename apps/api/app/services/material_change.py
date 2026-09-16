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

# Knowledge can change without requiring a new public article.
_KNOWLEDGE_ONLY_REASONS = {
    "status_confirmed",
    "evidence_posture_changed",
}
_EDITORIAL_REASONS = {
    "first_write",
    "new_high_claim",
    "new_medium_claim",
    "conflict_resolved",
    "status_conflict",
    "status_correction",
    "value_changed",
    "claim_removed_high",
}


def _enum_value(value: object) -> str:
    return value.value if hasattr(value, "value") else str(value)


def snapshot_claims(claims: Sequence[Claim], *, decisions: dict | None = None) -> list[dict]:
    rows: list[dict] = []
    for claim in sorted(claims, key=lambda row: str(row.id)):
        basis = ((decisions or {}).get(str(claim.id)) or {}).get("support_basis") or {}
        rows.append(
            {
                "id": str(claim.id),
                "canonical_text": claim.canonical_text,
                "status": _enum_value(claim.status),
                "importance": _enum_value(claim.importance),
                "normalized_value": claim.normalized_value,
                "claim_type": claim.claim_type,
                "evidence_posture": {key: basis.get(key) for key in (
                    "documents_supporting", "documents_qualifying", "documents_contradicting",
                    "known_independent_count", "unknown_group_count", "reprint_collapsed_count", "primary_access", "kind",
                )} if basis else None,
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
        if (row.get("importance") != ClaimImportance.LOW
                and row.get("evidence_posture") != before.get("evidence_posture")):
            before_posture = before.get("evidence_posture") or {}
            after_posture = row.get("evidence_posture") or {}
            before_contra = int(before_posture.get("documents_contradicting") or 0)
            after_contra = int(after_posture.get("documents_contradicting") or 0)
            if after_contra > before_contra:
                reasons.append("status_conflict")
            else:
                reasons.append("evidence_posture_changed")
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
    editorial = [reason for reason in unique if reason in _EDITORIAL_REASONS]
    return MaterialChange(is_material=bool(editorial), reasons=unique)


def build_knowledge_delta(
    previous: Sequence[dict] | None,
    current: Sequence[dict],
    change: MaterialChange,
) -> dict:
    prev_by_id = {str(row["id"]): row for row in previous or []}
    curr_by_id = {str(row["id"]): row for row in current}
    new_claims = [row for claim_id, row in curr_by_id.items() if claim_id not in prev_by_id]
    changed_claims: list[dict] = []
    changed_statuses: list[dict] = []
    new_conflicts: list[dict] = []
    resolved_conflicts: list[dict] = []
    corrected_values: list[dict] = []
    outdated_or_disproven: list[dict] = []
    for claim_id, row in curr_by_id.items():
        before = prev_by_id.get(claim_id)
        if before is None:
            continue
        entry = {"id": claim_id, "before": before, "after": row}
        if before != row:
            changed_claims.append(entry)
        if before.get("status") != row.get("status"):
            changed_statuses.append(
                {"id": claim_id, "from": before.get("status"), "to": row.get("status")}
            )
        before_status = _status(before["status"])
        after_status = _status(row["status"])
        if after_status == ClaimStatus.CONFLICTING and before_status != ClaimStatus.CONFLICTING:
            new_conflicts.append(row)
        if before_status == ClaimStatus.CONFLICTING and after_status in _RESOLVED:
            resolved_conflicts.append(row)
        if (before.get("normalized_value") or None) != (row.get("normalized_value") or None):
            corrected_values.append(entry)
        if after_status in _CORRECTION_TO and before_status not in _CORRECTION_TO:
            outdated_or_disproven.append(row)
    return {
        "new_claims": new_claims,
        "changed_claims": changed_claims,
        "changed_statuses": changed_statuses,
        "new_conflicts": new_conflicts,
        "resolved_conflicts": resolved_conflicts,
        "corrected_values": corrected_values,
        "outdated_or_disproven_claims": outdated_or_disproven,
        "material_reasons": list(change.reasons),
        "knowledge_only_reasons": [reason for reason in change.reasons if reason in _KNOWLEDGE_ONLY_REASONS],
    }
