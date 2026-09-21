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
    "normas", "normativas", "regulaciones", "disposiciones", "artículos",
    "ganó las elecciones", "resultado histórico", "asumió el cargo",
)
_JUDICIAL_RECORD_MARKERS = (
    "sobreseimiento",
    "sobreseyó",
    "sobreseyo",
    "sentencia",
    "fallo judicial",
    "procesamiento",
    "desestimó el recurso",
    "desestimo el recurso",
    "imputación formal",
    "imputacion formal",
    "fue condenad",
    "condenó a",
    "condeno a",
    "condenó al",
    "condeno al",
    "dictó sentencia",
    "dicto sentencia",
)
_JUDICIAL_FILING_MARKERS = (
    "denuncia penal",
    "presentó una denuncia",
    "presento una denuncia",
    "presentó denuncia",
    "presento denuncia",
    "radicó una denuncia",
    "radico una denuncia",
    "formuló una denuncia",
    "formulo una denuncia",
    "demanda judicial",
    "recurso de casación",
    "recurso de casacion",
    "recurso extraordinario",
)
_OBSERVABLE_COUNT_MARKERS = (
    "herido",
    "fallecid",
    "muerto",
    "evacuad",
    "detenido",
    "aprehendid",
    "vehiculo involucrad",
    "vehículo involucrad",
    "hectarea",
    "hectárea",
)
_MATERIAL_FIGURE_MARKERS = (
    "presupuesto",
    "inflacion",
    "inflación",
    "ipc",
    "desempleo",
    "deficit",
    "déficit",
    "deuda",
    "costo",
    "coste",
    "perdida",
    "pérdida",
    "patrimonio",
    "pbi",
    "producto bruto",
    "asistencia",
    "manifestantes",
    "concurrentes",
    "recaudacion",
    "recaudación",
    "inversion",
    "inversión",
    "subsidio",
    "millones",
    "resultado electoral",
    "padron",
    "padrón",
)
_SENSITIVE_ACCUSATION_MARKERS = (
    "corrupcion",
    "abuso",
    "delito",
    "fraude",
    "traicion",
    "homicidio",
    "violacion",
    "cohecho",
    "lavado de",
    "es culpable",
    "cometio",
    "cometió",
)
_ACCUSATION_TRUTH_VERBS = (
    "cometio",
    "cometió",
    "es culpable",
    "es responsable de",
    "perpetr",
    "traiciono",
    "traicionó",
)
_EXISTENCE_SHIELDS = (
    "denuncia penal",
    "presentó una denuncia",
    "presento una denuncia",
    "acusó a",
    "acuso a",
    "denunció a",
    "denuncio a",
    "imputó a",
    "imputo a",
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
    text = (getattr(claim, "canonical_text", None) or "").casefold()
    return any(marker in text for marker in _DOCUMENTARY_MARKERS)


def _claim_text(claim: Claim) -> str:
    return getattr(claim, "canonical_text", None) or ""


def looks_judicial_record(text: str) -> bool:
    folded = (text or "").casefold()
    return any(marker in folded for marker in _JUDICIAL_RECORD_MARKERS)


def looks_judicial_filing(text: str) -> bool:
    folded = (text or "").casefold()
    return any(marker in folded for marker in _JUDICIAL_FILING_MARKERS)


def is_observable_incident_count(text: str) -> bool:
    folded = (text or "").casefold()
    return any(marker in folded for marker in _OBSERVABLE_COUNT_MARKERS)


def is_material_figure(claim: Claim) -> bool:
    text = _claim_text(claim)
    folded = text.casefold()
    if any(marker in folded for marker in _MATERIAL_FIGURE_MARKERS):
        return True
    kind = canonicalize_claim_type(getattr(claim, "claim_type", None))
    if kind == "cifra" and not is_observable_incident_count(text):
        return True
    return False


def looks_sensitive_accusation(claim: Claim) -> bool:
    """Guilt/wrongdoing as fact. Imperfect classification still counts as sensitive."""
    from app.schemas.editorial_evidence import PropositionRole
    from app.services.claim_coverage import proposition_role_for

    text = _claim_text(claim)
    folded = text.casefold()
    try:
        role = proposition_role_for(claim)
    except Exception:
        role = None
    if role == PropositionRole.ACCUSATION_TRUTH:
        return True
    if any(marker in folded for marker in _EXISTENCE_SHIELDS):
        return False
    if canonicalize_claim_type(getattr(claim, "claim_type", None)) == "declaracion":
        return False
    if any(verb in folded for verb in _ACCUSATION_TRUTH_VERBS):
        return True
    return any(marker in folded for marker in _SENSITIVE_ACCUSATION_MARKERS) and any(
        verb in folded for verb in ("es ", "fue ", "comet", "responsable")
    )


def requires_authoritative_source(claim: Claim) -> bool:
    """True only if the intended editorial conclusion cannot be reached without a record."""
    from app.schemas.editorial_evidence import PropositionRole
    from app.services.claim_coverage import is_mixed_proposition, proposition_role_for

    text = _claim_text(claim)
    kind = canonicalize_claim_type(getattr(claim, "claim_type", None))
    if is_mixed_proposition(text, getattr(claim, "claim_type", None)):
        return True
    try:
        role = proposition_role_for(claim)
    except Exception:
        role = PropositionRole.OTHER
    if role == PropositionRole.UTTERANCE:
        return False
    if role in {PropositionRole.NORMATIVE_SCOPE, PropositionRole.EFFECTIVE_DATE, PropositionRole.ACCUSATION_TRUTH}:
        return True
    if looks_sensitive_accusation(claim):
        return True
    if looks_judicial_record(text):
        return True
    if role == PropositionRole.EXISTENCE or looks_judicial_filing(text):
        return False
    if kind == "documento":
        return True
    if is_material_figure(claim):
        return True
    folded = text.casefold()
    if any(marker in folded for marker in _DOCUMENTARY_MARKERS):
        if role == PropositionRole.UTTERANCE:
            return False
        if role == PropositionRole.EXISTENCE or (
            looks_judicial_filing(text) and not looks_judicial_record(text)
        ):
            return False
        return True
    return False


def is_well_supported(claim: Claim) -> bool:
    return claim.status == ClaimStatus.SUPPORTED and independent_support_count(claim) >= 2


def is_vetoed(claim: Claim, *, central: bool = False, flagged: bool = False) -> bool:
    if central or flagged:
        return claim.status in VETO_STATUSES
    if claim.status in VETO_STATUSES:
        return True
    kind = canonicalize_claim_type(claim.claim_type)
    if (
        kind in MUNDANE_TYPES
        and claim.importance != ClaimImportance.HIGH
        and claim.status in MUNDANE_STATUSES
        and not is_documentary_claim(claim)
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
    if (claim.importance == ClaimImportance.MEDIUM
            and claim.status in HARD_STATUSES and is_documentary_claim(claim)):
        return True
    if claim.importance == ClaimImportance.HIGH and claim.status == ClaimStatus.SINGLE_SOURCE:
        return True
    if claim.importance == ClaimImportance.HIGH and kind == "hecho":
        if is_documentary_claim(claim):
            return True
        return not well
    return False


CHEAP_LIVE_SKIP_REASONS = frozenset({"policy_skip", "budget"})


def cheap_live_evaluation_eligible(claim: Claim, *, skip_reason: str | None = None) -> bool:
    """HIGH well-supported hecho omitted from the paid-5 still needs a complete live contract.

    Does not copy a prior Verification decision. Declarations and vetoes stay skipped.
    """
    if skip_reason is not None and skip_reason not in CHEAP_LIVE_SKIP_REASONS:
        return False
    kind = canonicalize_claim_type(claim.claim_type)
    if kind != "hecho":
        return False
    if claim.importance != ClaimImportance.HIGH:
        return False
    if is_vetoed(claim):
        return False
    return is_well_supported(claim)


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
        if is_vetoed(claim, central=is_central, flagged=claim.id in flagged_ids):
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
