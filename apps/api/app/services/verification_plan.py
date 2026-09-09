from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone

from app.core.clock import utc_now
from app.core.config import get_settings
from app.domain.enums import ClaimImportance, ClaimStatus
from app.models import Claim
from app.schemas.verification import (
    CheapClaimEvidenceAssessment,
    EvidenceJudgementType,
    JudicialForum,
    SearchWindow,
    TemporalScope,
    VerificationPlan,
    VerificationSubject,
    VerificationTarget,
)
from app.services.evidence_source_registry import infer_judicial_forum, is_preferred_domain
from app.services.claim_coverage import is_mixed_proposition, proposition_role_for
from app.schemas.editorial_evidence import PropositionRole, StatementEvidenceClass
from app.services.information_origin import assess_origins, has_support_evidence
from app.services.verification_policy import (
    canonicalize_claim_type,
    independent_support_count,
    is_documentary_claim,
    is_well_supported,
)

_YEAR_RE = re.compile(r"\b((?:19|20)\d{2})\b")
_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")
_DATED_SCOPES = {
    TemporalScope.HISTORICAL,
    TemporalScope.EXACT_DATE,
    TemporalScope.EXACT_PERIOD,
}
_TARIFF_TOKENS = (
    "tarifa",
    "factura",
    "boleta",
    "bonificación",
    "bonificacion",
    "electricidad",
    "gas natural",
    "agua potable",
    "servicio de agua",
    "cloaca",
    "servicio público",
    "servicio publico",
    "ente regulador",
    "cuadro tarifario",
    "aumento tarifario",
    "revisión tarifaria",
    "revision tarifaria",
    "enre",
    "enargas",
    "eras",
    "aysa",
    "edenor",
    "edesur",
    "metrogas",
    "camuzzi",
)
_JUDICIAL_ACT_MARKERS = (
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
    "sobreseimiento",
    "sobreseyó",
    "sobreseyo",
    "sentencia",
    "fallo judicial",
    "procesamiento",
    "desestimó el recurso",
    "desestimo el recurso",
    "suprema corte",
    "corte suprema",
    "casación",
    "casacion",
)
_BELOW_MARKERS = ("por debajo", "menor que", "inferior a", "menos de", "menos que")
_ABOVE_MARKERS = ("por encima", "mayor que", "superior a", "más de", "mas de", "más que")


def year_hint_from_claim(claim: Claim) -> int | None:
    if claim.occurred_at is not None:
        return claim.occurred_at.year
    years = [int(match) for match in _YEAR_RE.findall(claim.canonical_text or "")]
    for row in getattr(claim, "evidence", None) or []:
        years.extend(int(match) for match in _YEAR_RE.findall(getattr(row, "excerpt", None) or ""))
    return min(years) if years else None


def temporal_scope_for_claim(claim: Claim, year_hint: int | None, *, now: datetime | None = None) -> TemporalScope:
    clock = now or utc_now()
    if claim.occurred_at is not None:
        when = claim.occurred_at
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
            clock = clock.replace(tzinfo=timezone.utc) if clock.tzinfo else clock
        age = clock - when
        if age <= timedelta(days=1):
            return TemporalScope.CURRENT
        if age <= timedelta(days=7):
            return TemporalScope.RECENT
        if age <= timedelta(days=31):
            return TemporalScope.EXACT_PERIOD
        return TemporalScope.HISTORICAL
    if year_hint is not None and year_hint <= clock.year - 2:
        return TemporalScope.HISTORICAL
    return TemporalScope.TIMELESS


def normalize_temporal_scope(plan: VerificationPlan, *, now: datetime | None = None) -> VerificationPlan:
    clock = now or utc_now()
    scope = plan.temporal_scope
    hint = plan.year_hint
    if hint is not None and hint >= clock.year and scope == TemporalScope.HISTORICAL:
        scope = TemporalScope.RECENT
    return plan.model_copy(update={"temporal_scope": scope})


def _looks_judicial_act(text: str) -> bool:
    return any(marker in text for marker in _JUDICIAL_ACT_MARKERS)


def _looks_regulated_tariff(text: str) -> bool:
    return any(token in text for token in _TARIFF_TOKENS)


def heuristic_plan(claim: Claim, *, jurisdiction: str | None = None) -> VerificationPlan:
    settings = get_settings()
    country = (jurisdiction or settings.editorial_country_code or "AR").strip().upper() or "AR"
    kind = canonicalize_claim_type(claim.claim_type)
    year_hint = year_hint_from_claim(claim)
    scope = temporal_scope_for_claim(claim, year_hint)
    target = VerificationTarget.GENERAL_WEB
    subject = VerificationSubject.GENERAL
    primary = False
    corroboration = False
    forum = JudicialForum.UNKNOWN
    text = (claim.canonical_text or "").lower()
    if _looks_judicial_act(text):
        target = VerificationTarget.JUDICIAL_RECORD
        subject = VerificationSubject.JUDICIAL_CASE
        primary = True
        try:
            forum = JudicialForum(infer_judicial_forum(claim.canonical_text))
        except ValueError:
            forum = JudicialForum.UNKNOWN
    elif kind == "documento":
        target = VerificationTarget.OFFICIAL_RECORD
        subject = VerificationSubject.LAW_OR_DECREE
        primary = True
    elif kind == "cifra":
        if _looks_regulated_tariff(text):
            target = VerificationTarget.OFFICIAL_RECORD
            subject = VerificationSubject.REGULATED_TARIFF
        else:
            target = VerificationTarget.OFFICIAL_STATISTICS
            subject = VerificationSubject.STATISTICS
        primary = True
    elif kind == "declaracion":
        if is_mixed_proposition(claim.canonical_text or "", claim.claim_type):
            target = VerificationTarget.INDEPENDENT_CORROBORATION
            subject = VerificationSubject.GENERAL
            primary = True
            corroboration = True
        else:
            target = VerificationTarget.PRIMARY_STATEMENT
            subject = VerificationSubject.PUBLIC_STATEMENT
    elif kind == "hecho" and claim.importance == ClaimImportance.HIGH:
        if claim.status in {ClaimStatus.SINGLE_SOURCE, ClaimStatus.UNCERTAIN, ClaimStatus.CONFLICTING}:
            subject = VerificationSubject.ACCUSATION
            target = VerificationTarget.INDEPENDENT_CORROBORATION
            corroboration = True
    return normalize_temporal_scope(
        VerificationPlan(
            verification_target=target,
            temporal_scope=scope,
            subject=subject,
            jurisdiction=country,
            primary_source_required=primary,
            independent_corroboration_required=corroboration,
            year_hint=year_hint,
            search_terms=[],
            judicial_forum=forum,
        )
    )


def _choose_year_hint(planned: VerificationPlan, fallback: VerificationPlan, *, now: datetime) -> int | None:
    planned_year = planned.year_hint
    fallback_year = fallback.year_hint
    if planned_year is None:
        return fallback_year
    if fallback_year is None:
        return planned_year
    if planned_year >= now.year and fallback_year < now.year:
        return fallback_year
    return planned_year


def refine_plan(
    planned: VerificationPlan,
    fallback: VerificationPlan,
    *,
    claim: Claim | None = None,
    now: datetime | None = None,
) -> VerificationPlan:
    """Keep LLM structure, but correct impossible temporal/target combinations in code."""
    clock = now or utc_now()
    year_hint = _choose_year_hint(planned, fallback, now=clock)
    scope = planned.temporal_scope
    if fallback.temporal_scope == TemporalScope.HISTORICAL and scope in {
        TemporalScope.CURRENT,
        TemporalScope.RECENT,
    }:
        scope = TemporalScope.HISTORICAL
    if (
        fallback.temporal_scope == TemporalScope.TIMELESS
        and year_hint is None
        and scope in {TemporalScope.CURRENT, TemporalScope.RECENT}
    ):
        scope = TemporalScope.TIMELESS
    target = planned.verification_target
    subject = planned.subject
    forum = planned.judicial_forum
    primary = planned.primary_source_required or fallback.primary_source_required
    corroboration = planned.independent_corroboration_required or fallback.independent_corroboration_required
    mixed = False
    role = None
    if claim is not None:
        mixed = is_mixed_proposition(claim.canonical_text or "", claim.claim_type)
        role = proposition_role_for(claim)
    if fallback.subject == VerificationSubject.REGULATED_TARIFF:
        subject = fallback.subject
        if planned.verification_target == VerificationTarget.OFFICIAL_STATISTICS:
            target = fallback.verification_target
        elif planned.verification_target in {
            VerificationTarget.OFFICIAL_RECORD,
            VerificationTarget.OFFICIAL_LAW,
        }:
            target = planned.verification_target
        else:
            target = fallback.verification_target
    if fallback.verification_target == VerificationTarget.JUDICIAL_RECORD:
        target = fallback.verification_target
        subject = fallback.subject
        if fallback.judicial_forum != JudicialForum.UNKNOWN:
            forum = fallback.judicial_forum
        elif planned.judicial_forum == JudicialForum.UNKNOWN:
            forum = fallback.judicial_forum
    if (
        claim is not None
        and not mixed
        and (
            fallback.subject == VerificationSubject.PUBLIC_STATEMENT
            or role == PropositionRole.UTTERANCE
            or canonicalize_claim_type(claim.claim_type) == "declaracion"
        )
    ):
        target = VerificationTarget.PRIMARY_STATEMENT
        subject = VerificationSubject.PUBLIC_STATEMENT
        primary = False
        corroboration = False
    return normalize_temporal_scope(
        planned.model_copy(
            update={
                "year_hint": year_hint,
                "temporal_scope": scope,
                "verification_target": target,
                "subject": subject,
                "judicial_forum": forum,
                "independent_corroboration_required": corroboration,
                "primary_source_required": primary,
            }
        ),
        now=clock,
    )


def is_numeric_comparison_claim(claim: Claim) -> bool:
    text = (claim.canonical_text or "").casefold()
    return any(marker in text for marker in _BELOW_MARKERS) or any(
        marker in text for marker in _ABOVE_MARKERS
    )


def _parse_magnitudes(text: str) -> list[float]:
    values: list[float] = []
    for raw in _NUMBER_RE.findall(text or ""):
        if re.fullmatch(r"(?:19|20)\d{2}", raw):
            continue
        values.append(float(raw.replace(",", ".")))
    return values


def _claim_magnitudes(claim: Claim) -> list[float]:
    values = _parse_magnitudes(claim.canonical_text or "")
    raw = getattr(claim, "normalized_value", None)
    if raw:
        try:
            parsed = float(str(raw).replace(",", "."))
        except ValueError:
            parsed = None
        if parsed is not None and parsed not in values:
            values.append(parsed)
    return values


def try_resolve_numeric_comparison(
    claim: Claim,
    siblings: Sequence[Claim] | None = None,
) -> ClaimStatus | None:
    text = (claim.canonical_text or "").casefold()
    if any(marker in text for marker in _BELOW_MARKERS):
        direction = "lt"
    elif any(marker in text for marker in _ABOVE_MARKERS):
        direction = "gt"
    else:
        return None
    own = _claim_magnitudes(claim)
    if not own:
        return None
    extras: list[float] = []
    for sibling in siblings or []:
        if getattr(sibling, "id", None) == getattr(claim, "id", None):
            continue
        if canonicalize_claim_type(getattr(sibling, "claim_type", None)) != "cifra":
            continue
        if getattr(sibling, "status", None) != ClaimStatus.SUPPORTED:
            continue
        extras.extend(_claim_magnitudes(sibling))
    threshold = own[-1]
    left = [value for value in extras if value != threshold]
    if not left:
        return None
    matched = all(value < threshold for value in left) if direction == "lt" else all(value > threshold for value in left)
    return ClaimStatus.SUPPORTED if matched else ClaimStatus.DISPROVEN


def freshness_for_plan(plan: VerificationPlan) -> str | None:
    if plan.temporal_scope == TemporalScope.CURRENT:
        return "pd"
    if plan.temporal_scope == TemporalScope.RECENT:
        return "pw"
    return None


def date_bounds_for_plan(plan: VerificationPlan, claim: Claim) -> tuple[datetime | None, datetime | None]:
    if plan.temporal_scope == TemporalScope.EXACT_DATE and claim.occurred_at is not None:
        when = claim.occurred_at
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return when - timedelta(days=1), when + timedelta(days=1)
    if plan.temporal_scope == TemporalScope.EXACT_PERIOD and plan.year_hint:
        start = datetime(plan.year_hint, 1, 1, tzinfo=timezone.utc)
        end = datetime(plan.year_hint, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
        return start, end
    return None, None


def search_window_for(plan: VerificationPlan, claim: Claim, *, now: datetime | None = None) -> SearchWindow:
    clock = now or utc_now()
    if plan.year_hint is not None and plan.year_hint <= clock.year - 2:
        return SearchWindow(freshness=None, since=None, until=None)
    if plan.temporal_scope in {TemporalScope.HISTORICAL, TemporalScope.TIMELESS}:
        since, until = date_bounds_for_plan(plan, claim)
        return SearchWindow(freshness=None, since=since, until=until)
    since, until = date_bounds_for_plan(plan, claim)
    return SearchWindow(freshness=freshness_for_plan(plan), since=since, until=until)


def core_search_text(claim: Claim, plan: VerificationPlan) -> str:
    terms = [token.strip() for token in plan.search_terms if token and token.strip()]
    if terms:
        parts = [f'"{token}"' if " " in token else token for token in terms[:4]]
        core = " ".join(parts)
    else:
        core = (claim.canonical_text or "").strip()
    if (
        plan.year_hint
        and str(plan.year_hint) not in core
        and plan.temporal_scope in _DATED_SCOPES
    ):
        core = f"{core} {plan.year_hint}".strip()
    return core


def build_verification_queries(
    claim: Claim,
    plan: VerificationPlan,
    domains: list[str],
    *,
    limit: int = 3,
) -> list[str]:
    core = core_search_text(claim, plan)
    if not core:
        return []
    queries: list[str] = []
    site_slots = max(0, limit - 1)
    for domain in domains[:site_slots]:
        queries.append(f"{core} site:{domain}")
    queries.append(core)
    seen: set[str] = set()
    unique: list[str] = []
    for query in queries:
        if query in seen:
            continue
        seen.add(query)
        unique.append(query)
    return unique[: max(0, limit)]


def claim_has_preferred_evidence(claim: Claim, preferred: list[str]) -> bool:
    if not preferred:
        return False
    for row in getattr(claim, "evidence", None) or []:
        item = getattr(row, "source_item", None)
        url = ""
        if item is not None:
            url = item.canonical_url or item.url or ""
        if not url:
            url = getattr(row, "source_url", None) or ""
        if url and is_preferred_domain(url, preferred):
            return True
    return False


def skip_directed_search(claim: Claim, plan: VerificationPlan, preferred: list[str]) -> bool:
    if claim.status != ClaimStatus.SUPPORTED:
        return False
    if independent_support_count(claim) < 2:
        return False
    if plan.independent_corroboration_required:
        return False
    if plan.subject == VerificationSubject.ACCUSATION:
        return False
    if plan.primary_source_required and not claim_has_preferred_evidence(claim, preferred):
        return False
    return True


def assessment_has_conflict(assessment: CheapClaimEvidenceAssessment) -> bool:
    relations = {row.relation for row in assessment.judgements}
    return EvidenceJudgementType.CONTRADICTS in relations


def assessment_has_support(assessment: CheapClaimEvidenceAssessment) -> bool:
    return any(row.relation == EvidenceJudgementType.SUPPORTS for row in assessment.judgements)


def needs_sol_after_assessment(
    claim: Claim,
    plan: VerificationPlan,
    assessment: CheapClaimEvidenceAssessment | None,
    *,
    primary_support: bool,
) -> bool:
    if assessment is None:
        return True
    if assessment.ambiguous:
        return True
    if assessment_has_conflict(assessment):
        return True
    supports = assessment_has_support(assessment)
    if plan.primary_source_required and not primary_support:
        if is_well_supported(claim):
            return False
        return True
    if plan.independent_corroboration_required and independent_support_count(claim) < 2:
        return True
    if not supports:
        if plan.primary_source_required or plan.independent_corroboration_required:
            return True
        if claim.status in {ClaimStatus.UNCERTAIN, ClaimStatus.CONFLICTING}:
            return True
        return False
    return False


def apply_primary_requirement(
    claim: Claim,
    status: ClaimStatus,
    plan: VerificationPlan,
    *,
    primary_supports: bool,
) -> ClaimStatus:
    if status != ClaimStatus.SUPPORTED:
        return status
    assessment = assess_origins(claim)
    count = assessment.known_independent
    has_support = has_support_evidence(claim)
    mixed = is_mixed_proposition(claim.canonical_text or "", claim.claim_type)
    role = proposition_role_for(claim)
    if mixed:
        if plan.primary_source_required and not primary_supports:
            return ClaimStatus.SINGLE_SOURCE if has_support else ClaimStatus.UNCERTAIN
        if count >= 2:
            return ClaimStatus.SUPPORTED
        return ClaimStatus.SINGLE_SOURCE if has_support else ClaimStatus.UNCERTAIN
    if role == PropositionRole.UTTERANCE or plan.subject == VerificationSubject.PUBLIC_STATEMENT:
        if assessment.statement_evidence_class == StatementEvidenceClass.AUTHENTIC_PRIMARY:
            return ClaimStatus.SUPPORTED
        if plan.primary_source_required and not primary_supports:
            return ClaimStatus.SINGLE_SOURCE if has_support else ClaimStatus.UNCERTAIN
        if count >= 2:
            return ClaimStatus.SUPPORTED
        return ClaimStatus.SINGLE_SOURCE if has_support else ClaimStatus.UNCERTAIN
    if plan.primary_source_required and not primary_supports:
        if claim.status == ClaimStatus.SUPPORTED and count >= 2:
            return ClaimStatus.SUPPORTED
        return ClaimStatus.SINGLE_SOURCE if has_support else ClaimStatus.UNCERTAIN
    if primary_supports and (is_documentary_claim(claim) or plan.primary_source_required):
        return ClaimStatus.SUPPORTED
    if count >= 2:
        return ClaimStatus.SUPPORTED
    if has_support:
        return ClaimStatus.SINGLE_SOURCE
    return ClaimStatus.UNCERTAIN
