from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from app.core.clock import utc_now
from app.core.config import get_settings
from app.domain.enums import ClaimImportance, ClaimStatus
from app.models import Claim
from app.schemas.verification import (
    CheapClaimEvidenceAssessment,
    EvidenceJudgementType,
    SearchWindow,
    TemporalScope,
    VerificationPlan,
    VerificationSubject,
    VerificationTarget,
)
from app.services.evidence_source_registry import is_preferred_domain
from app.services.verification_policy import canonicalize_claim_type, independent_support_count

_YEAR_RE = re.compile(r"\b((?:19|20)\d{2})\b")
_DATED_SCOPES = {
    TemporalScope.HISTORICAL,
    TemporalScope.EXACT_DATE,
    TemporalScope.EXACT_PERIOD,
}


def year_hint_from_claim(claim: Claim) -> int | None:
    if claim.occurred_at is not None:
        return claim.occurred_at.year
    years = [int(match) for match in _YEAR_RE.findall(claim.canonical_text or "")]
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
    if kind == "documento":
        target = VerificationTarget.OFFICIAL_RECORD
        subject = VerificationSubject.LAW_OR_DECREE
        primary = True
    elif kind == "cifra":
        text = (claim.canonical_text or "").lower()
        looks_stat = any(
            token in text for token in ("ipc", "indec", "desempleo", "pobreza", "inflación", "inflacion")
        )
        looks_tariff = any(
            token in text for token in ("tarifa", "factura", "bonificación", "bonificacion")
        )
        if looks_tariff and not looks_stat:
            target = VerificationTarget.OFFICIAL_LAW
            subject = VerificationSubject.LAW_OR_DECREE
        else:
            target = VerificationTarget.OFFICIAL_STATISTICS
            subject = VerificationSubject.STATISTICS
        primary = True
    elif kind == "declaracion":
        target = VerificationTarget.PRIMARY_STATEMENT
        subject = VerificationSubject.PUBLIC_STATEMENT
    elif kind == "hecho" and claim.importance == ClaimImportance.HIGH:
        text = (claim.canonical_text or "").lower()
        if any(
            token in text
            for token in ("sobreseimiento", "sobreseyó", "sobreseyo", "casación", "casacion")
        ):
            target = VerificationTarget.JUDICIAL_RECORD
            subject = VerificationSubject.JUDICIAL_CASE
            primary = True
        elif claim.status in {ClaimStatus.SINGLE_SOURCE, ClaimStatus.UNCERTAIN, ClaimStatus.CONFLICTING}:
            subject = VerificationSubject.ACCUSATION
            target = VerificationTarget.INDEPENDENT_CORROBORATION
            corroboration = True
    return VerificationPlan(
        verification_target=target,
        temporal_scope=scope,
        subject=subject,
        jurisdiction=country,
        primary_source_required=primary,
        independent_corroboration_required=corroboration,
        year_hint=year_hint,
        search_terms=[],
    )


def refine_plan(planned: VerificationPlan, fallback: VerificationPlan) -> VerificationPlan:
    """Keep LLM structure, but don't copy the Event's recency onto an undated/historical Claim."""
    year_hint = planned.year_hint if planned.year_hint is not None else fallback.year_hint
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
    if (
        fallback.verification_target == VerificationTarget.OFFICIAL_LAW
        and planned.verification_target == VerificationTarget.OFFICIAL_STATISTICS
    ):
        target = fallback.verification_target
        subject = fallback.subject
    if (
        fallback.verification_target == VerificationTarget.JUDICIAL_RECORD
        and planned.verification_target
        in {VerificationTarget.OFFICIAL_RECORD, VerificationTarget.GENERAL_WEB}
    ):
        target = fallback.verification_target
        subject = fallback.subject
    return planned.model_copy(
        update={
            "year_hint": year_hint,
            "temporal_scope": scope,
            "verification_target": target,
            "subject": subject,
            "independent_corroboration_required": (
                planned.independent_corroboration_required or fallback.independent_corroboration_required
            ),
            "primary_source_required": planned.primary_source_required or fallback.primary_source_required,
        }
    )


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


def search_window_for(plan: VerificationPlan, claim: Claim) -> SearchWindow:
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
