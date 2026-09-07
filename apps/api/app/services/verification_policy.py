from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.core.text import normalize_name, token_set
from app.core.urls import url_domain
from app.domain.enums import ClaimImportance, ClaimStatus, EvidenceType
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
_WEAK_INDEPENDENT_HOSTS = (
    "blogspot.com",
    "blogger.com",
    "wordpress.com",
    "tumblr.com",
    "medium.com",
    "substack.com",
)
_REPRINT_CONTAINMENT = 0.85
_REPRINT_MIN_TOKENS = 8


def canonicalize_claim_type(raw: str | None) -> str:
    token = normalize_name(raw or "")
    if not token:
        return "hecho"
    token = TYPE_ALIASES.get(token, token)
    if token not in CANONICAL_TYPES:
        return "hecho"
    return token


def _is_weak_independent_host(domain: str) -> bool:
    token = (domain or "").strip().lower()
    if token.startswith("www."):
        token = token[4:]
    return any(token == host or token.endswith("." + host) for host in _WEAK_INDEPENDENT_HOSTS)


def _support_domain(row) -> str:
    item = getattr(row, "source_item", None)
    domain = ""
    if item is not None:
        source = getattr(item, "source", None)
        if source is not None and getattr(source, "domain", None):
            domain = source.domain
        if not domain:
            domain = url_domain(getattr(item, "canonical_url", None) or getattr(item, "url", "") or "")
    if not domain:
        domain = url_domain(getattr(row, "source_url", None) or "")
    return (domain or "").strip().lower()


def _reprint_of(tokens_a: set[str], tokens_b: set[str]) -> bool:
    if len(tokens_a) < _REPRINT_MIN_TOKENS or len(tokens_b) < _REPRINT_MIN_TOKENS:
        return False
    overlap = len(tokens_a & tokens_b)
    return overlap / min(len(tokens_a), len(tokens_b)) >= _REPRINT_CONTAINMENT


def independent_support_count(claim: Claim) -> int:
    rows: list[tuple[str, set[str]]] = []
    for row in getattr(claim, "evidence", None) or []:
        if getattr(row, "evidence_type", None) != EvidenceType.SUPPORTS:
            continue
        domain = _support_domain(row)
        if not domain or _is_weak_independent_host(domain):
            continue
        excerpt = getattr(row, "excerpt", None) or ""
        rows.append((domain, token_set(excerpt)))

    used = [False] * len(rows)
    count = 0
    for index, (domain, tokens) in enumerate(rows):
        if used[index]:
            continue
        used[index] = True
        count += 1
        for other, (other_domain, other_tokens) in enumerate(rows[index + 1 :], start=index + 1):
            if used[other]:
                continue
            if other_domain == domain or _reprint_of(tokens, other_tokens):
                used[other] = True
    return count


def is_well_supported(claim: Claim) -> bool:
    return claim.status == ClaimStatus.SUPPORTED and independent_support_count(claim) >= 2


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
    well = is_well_supported(claim)
    if kind == "declaracion":
        return not well
    if kind in HARD_TYPES and claim.importance == ClaimImportance.HIGH:
        return True
    if claim.importance == ClaimImportance.HIGH and claim.status == ClaimStatus.SINGLE_SOURCE:
        return True
    if claim.importance == ClaimImportance.HIGH and kind == "hecho":
        return not well
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
