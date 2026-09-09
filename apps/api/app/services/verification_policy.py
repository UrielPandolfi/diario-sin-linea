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
_DOCUMENTARY_MARKERS = (
    "decreto",
    "designó",
    "designe",
    "designacion",
    "designación",
    "nombramiento",
    "resolución",
    "resolucion",
    "sentencia",
    "fallo judicial",
    "sobreseimiento",
    "sobreseyó",
    "sobreseyo",
    "presupuesto",
    "boletín",
    "boletin",
    "indec",
    "juzgado",
    "camara federal",
    "cámara federal",
    "suprema corte",
    "corte suprema",
    "casación",
    "casacion",
    "procesamiento",
    "ley ",
    "padrón",
    "padron",
    "resultado electoral",
    "documento administrativo",
)
_WEAK_INDEPENDENT_HOSTS = (
    "blogspot.com",
    "blogger.com",
    "wordpress.com",
    "tumblr.com",
    "medium.com",
    "substack.com",
)


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


def independent_support_count(claim: Claim) -> int:
    from app.services.information_origin import independent_support_count as origin_count

    return origin_count(claim)


def is_documentary_claim(claim: Claim) -> bool:
    kind = canonicalize_claim_type(claim.claim_type)
    if kind in HARD_TYPES:
        return True
    text = (claim.canonical_text or "").casefold()
    return any(marker in text for marker in _DOCUMENTARY_MARKERS)


def is_well_supported(claim: Claim) -> bool:
    return claim.status == ClaimStatus.SUPPORTED and independent_support_count(claim) >= 2


def is_vetoed(claim: Claim, *, central: bool = False) -> bool:
    if central:
        return claim.status in VETO_STATUSES
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
        if is_documentary_claim(claim):
            return True
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
    central_ids: set[UUID] | None = None,
) -> tuple[list[SelectedClaim], list[dict]]:
    centrals = central_ids or set()
    selected: list[SelectedClaim] = []
    skipped: list[dict] = []
    for claim in claims:
        is_central = claim.id in centrals
        if is_vetoed(claim, central=is_central):
            skipped.append({"claim_id": str(claim.id), "reason": "veto"})
            continue
        reasons: list[str] = []
        if is_central:
            reasons.append("central")
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
            0 if claim.id in centrals else 1,
            0 if "m5_flag" in row.reasons else 1,
            0 if claim.importance == ClaimImportance.HIGH else 1,
            0 if kind in PRIORITY_TYPES else 1,
            str(claim.id),
        )

    selected.sort(key=_sort_key)
    kept = selected[: max(0, limit)]
    for row in selected[max(0, limit) :]:
        skipped.append({"claim_id": str(row.claim.id), "reason": "budget"})
    return kept, skipped
