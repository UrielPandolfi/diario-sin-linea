from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.core.text import normalize_name
from app.domain.enums import ClaimImportance, ClaimStatus
from app.models import Claim

CANONICAL_TYPES = frozenset({"hecho", "estado", "declaracion", "cifra", "documento"})
TYPE_ALIASES = {
    "cita": "declaracion",
    "estadistica": "cifra",
    "presupuesto": "cifra",
    "ley": "documento",
    "decreto": "documento",
}
MUNDANE_TYPES = frozenset({"hecho", "estado"})
HARD_TYPES = frozenset({"cifra", "documento"})
PRIORITY_TYPES = frozenset({"declaracion", "cifra", "documento"})
VETO_STATUSES = frozenset({ClaimStatus.OUTDATED, ClaimStatus.DISPROVEN})
MUNDANE_STATUSES = frozenset({ClaimStatus.SUPPORTED, ClaimStatus.SINGLE_SOURCE})
HARD_STATUSES = frozenset({ClaimStatus.SINGLE_SOURCE, ClaimStatus.UNCERTAIN, ClaimStatus.CONFLICTING})


def canonicalize_claim_type(raw: str | None) -> str:
    token = normalize_name(raw or "")
    if not token:
        return "hecho"
    token = TYPE_ALIASES.get(token, token)
    if token not in CANONICAL_TYPES:
        return "hecho"
    return token


def is_vetoed(claim: Claim) -> bool:
    if claim.status in VETO_STATUSES:
        return True
    kind = canonicalize_claim_type(claim.claim_type)
    if (
        kind in MUNDANE_TYPES
        and claim.importance != ClaimImportance.HIGH
        and claim.status in MUNDANE_STATUSES
    ):
        return True
    return False


def policy_selects(claim: Claim) -> bool:
    kind = canonicalize_claim_type(claim.claim_type)
    if kind == "declaracion":
        return True
    if kind in HARD_TYPES and claim.importance == ClaimImportance.HIGH and claim.status in HARD_STATUSES:
        return True
    if claim.importance == ClaimImportance.HIGH and claim.status == ClaimStatus.SINGLE_SOURCE:
        return True
    return False


@dataclass(frozen=True)
class SelectedClaim:
    claim: Claim
    reasons: list[str]


def select_claims(
    claims: list[Claim],
    *,
    flagged_ids: set[UUID],
    limit: int,
) -> tuple[list[SelectedClaim], list[dict]]:
    selected: list[SelectedClaim] = []
    skipped: list[dict] = []
    for claim in claims:
        if is_vetoed(claim):
            skipped.append({"claim_id": str(claim.id), "reason": "veto"})
            continue
        reasons: list[str] = []
        if claim.id in flagged_ids:
            reasons.append("m5_flag")
        if policy_selects(claim):
            kind = canonicalize_claim_type(claim.claim_type)
            reasons.append(f"policy:{kind}")
        if reasons:
            selected.append(SelectedClaim(claim=claim, reasons=reasons))
        else:
            skipped.append({"claim_id": str(claim.id), "reason": "policy_skip"})

    def _sort_key(row: SelectedClaim) -> tuple:
        claim = row.claim
        kind = canonicalize_claim_type(claim.claim_type)
        return (
            0 if "m5_flag" in row.reasons else 1,
            0 if claim.importance == ClaimImportance.HIGH else 1,
            0 if kind in PRIORITY_TYPES else 1,
            str(claim.id),
        )

    selected.sort(key=_sort_key)
    return selected[: max(0, limit)], skipped
