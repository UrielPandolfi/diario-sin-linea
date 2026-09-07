from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from app.domain.enums import ClaimStatus, EditorialLabel, EvidenceType
from app.models import Claim
from app.services.claim_service import assertion_key_for, comparison_key_for
from app.services.verification_outcome import VerificationView, is_strong_verification


@dataclass
class ClaimEditorial:
    labels: list[EditorialLabel] = field(default_factory=list)
    false_assertions: list[dict[str, Any]] = field(default_factory=list)


def is_checked(claim: Claim, view: VerificationView) -> bool:
    return claim.status == ClaimStatus.SUPPORTED and is_strong_verification(claim.id, view)


def labels_for_event_claims(claims: list[Claim], view: VerificationView) -> dict[str, ClaimEditorial]:
    groups: dict[str, list[Claim]] = defaultdict(list)
    for claim in claims:
        groups[comparison_key_for(claim)].append(claim)
    checked = {str(claim.id) for claim in claims if is_checked(claim, view)}
    result: dict[str, ClaimEditorial] = {}
    for claim in claims:
        members = groups[comparison_key_for(claim)]
        group_checked = any(str(member.id) in checked for member in members)
        discrepancy = _intra_discrepancy(claim) or _competitor_discrepancy(members)
        labels: list[EditorialLabel] = []
        if str(claim.id) in checked:
            labels.append(EditorialLabel.CHECKED)
        if discrepancy:
            labels.append(EditorialLabel.DISCREPANCY)
        if discrepancy and not group_checked:
            labels.append(EditorialLabel.DISPUTED)
        false_assertions: list[dict[str, Any]] = []
        if claim.status == ClaimStatus.DISPROVEN and group_checked:
            winner = next((member for member in members if str(member.id) in checked), None)
            if winner is not None and _false_claim_pair(winner, claim):
                labels.append(EditorialLabel.FALSE_CLAIM)
        if str(claim.id) in checked:
            for sibling in members:
                if sibling.status == ClaimStatus.DISPROVEN and _false_claim_pair(claim, sibling):
                    false_assertions.extend(_assertions_from(sibling))
        result[str(claim.id)] = ClaimEditorial(labels=labels, false_assertions=_dedupe_assertions(false_assertions))
    return result


def editorial_public_payload(editorial: ClaimEditorial | None) -> dict[str, Any]:
    if editorial is None:
        return {"editorial_labels": [], "false_assertions": []}
    return {
        "editorial_labels": [label.value for label in editorial.labels],
        "false_assertions": editorial.false_assertions,
    }


def _has_structured_spo(claim: Claim) -> bool:
    return bool((getattr(claim, "subject", None) or "").strip() and (getattr(claim, "predicate", None) or "").strip())


def _same_temporal_context(left: Claim, right: Claim) -> bool:
    if left.occurred_at is None and right.occurred_at is None:
        return True
    if left.occurred_at is None or right.occurred_at is None:
        return False
    return left.occurred_at == right.occurred_at


def _intra_discrepancy(claim: Claim) -> bool:
    supports: set[UUID | None] = set()
    contradicts: set[UUID | None] = set()
    for row in getattr(claim, "evidence", None) or []:
        if row.evidence_type == EvidenceType.SUPPORTS:
            supports.add(row.source_item_id)
        elif row.evidence_type == EvidenceType.CONTRADICTS:
            contradicts.add(row.source_item_id)
    return bool(supports and contradicts)


def _competitor_discrepancy(members: list[Claim]) -> bool:
    keys = {assertion_key_for(claim) for claim in members}
    if len(keys) < 2:
        return False
    live = [claim for claim in members if claim.status != ClaimStatus.OUTDATED]
    return len({assertion_key_for(claim) for claim in live}) >= 2


def _false_claim_pair(winner: Claim, loser: Claim) -> bool:
    if loser.status != ClaimStatus.DISPROVEN:
        return False
    if winner.status != ClaimStatus.SUPPORTED:
        return False
    if comparison_key_for(winner) != comparison_key_for(loser):
        return False
    if assertion_key_for(winner) == assertion_key_for(loser):
        return False
    if not _has_structured_spo(winner) or not _has_structured_spo(loser):
        return False
    if not _same_temporal_context(winner, loser):
        return False
    return any(
        row.evidence_type == EvidenceType.SUPPORTS and (row.excerpt or "").strip()
        for row in getattr(loser, "evidence", None) or []
    )


def _assertions_from(claim: Claim) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in getattr(claim, "evidence", None) or []:
        if row.evidence_type != EvidenceType.SUPPORTS:
            continue
        excerpt = (row.excerpt or "").strip()
        if not excerpt:
            continue
        item = getattr(row, "source_item", None)
        source = getattr(item, "source", None) if item is not None else None
        name = getattr(source, "name", None) or getattr(source, "domain", None)
        url = row.source_url or (getattr(item, "url", None) if item is not None else None)
        rows.append(
            {
                "source_item_id": str(row.source_item_id),
                "source_name": name or url or "Fuente",
                "source_url": url,
                "excerpt": excerpt,
            }
        )
    return rows


def _dedupe_assertions(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for row in rows:
        key = str(row.get("source_item_id") or "")
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique
