from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.clock import utc_now
from app.core.config import get_settings
from app.core.prompts import load_prompt
from app.core.source_content import (
    BODY_SOURCE_EXTRACTED_HTML,
    BODY_SOURCE_SEARCH_SNIPPET,
    BODY_SOURCE_TITLE_ONLY,
    is_extracted_body,
    merge_item_metadata,
)
from app.core.source_snippet import select_source_snippet
from app.core.text import content_fingerprint, excerpt_in_source, postgres_safe_json, postgres_safe_text, token_set
from app.core.urls import canonicalize_url, url_domain
from app.core.usage_context import usage_scope
from app.domain.enums import (
    ClaimStatus,
    EventSourceRelation,
    EvidenceType,
    IngestionMethod,
    PipelineStatus,
)
from app.models import Claim, ClaimEvidence, Event, EventSource, PipelineRun, Source, SourceItem
from app.providers.base import (
    ProviderNotConfiguredError,
    SearchHit,
    SearchProvider,
    SearchQuery,
    StructuredLLMProvider,
)
from app.providers.rate_limit import is_transient_http_error
from app.providers.registry import (
    ModelRole,
    get_search_provider,
    get_structured_provider,
    get_structured_provider_optional,
)
from app.repositories import (
    PipelineRunRepository,
    SourceItemRepository,
    SourceRepository,
)
from app.schemas import SourceCreate, SourceItemCreate
from app.schemas.verification import (
    CheapClaimEvidenceAssessment,
    CheapEvidenceJudgement,
    EVENT_SOURCE_EVIDENCE_TYPES,
    PERSISTABLE_JUDGEMENTS,
    VerificationPlan,
    VerificationResult,
)
from app.schemas.editorial_evidence import (
    CONTRACT_VERSION,
    ClaimDecision,
    CoverageContract,
    Demotion,
    PrimaryAccess,
    PropositionRole,
    StatementEvidenceClass,
    VerificationBudget,
)
from app.services.claim_coverage import (
    central_claim_ids,
    claims_fingerprint,
    evaluated_claims_payload,
    is_mixed_proposition,
    proposition_role_for,
)
from app.services.claim_service import CLAIM_STAGE, assertion_key_for, comparison_key_for, is_utterance_claim
from app.services.information_origin import (
    assess_origins,
    demotion_for,
    final_reason_for,
    support_basis_from_assessment,
    usable_body_source,
)
from app.services.event_service import EventService
from app.services.evidence_source_registry import is_preferred_domain, preferred_domains
from app.services.fetching import HttpFetcher, extract_text, is_extractable_document
from app.services.source_item_service import SourceItemService
from app.services.source_service import SourceService
from app.services.verification_plan import (
    apply_primary_requirement,
    assessment_has_support,
    build_verification_searches,
    is_regulatory_count,
    claim_has_preferred_evidence,
    heuristic_plan,
    is_numeric_comparison_claim,
    needs_sol_after_assessment,
    refine_plan,
    search_window_for,
    skip_directed_search,
    try_resolve_numeric_comparison,
)
from app.services.verification_outcome import (
    VERIFICATION_STAGE,
    is_strong_verification,
    latest_success_claim_resolution,
    view_from_mapping,
)
from app.services.verification_policy import canonicalize_claim_type, select_claims
from app.services.verification_policy import SelectedClaim
from app.services.claim_meaning import attributed_statement, temporal_comparison
from app.services.evidence_comparison import COMPARISON_POLICY_VERSION, valid_contradiction

SNIPPET_CHARS = 1500
_PLANNER_ERRORS = (ProviderNotConfiguredError, ValidationError, ValueError, KeyError, RuntimeError)


@dataclass
class _PacketSource:
    ref: int
    url: str
    title: str
    snippet: str
    item: SourceItem | None = None
    hit: SearchHit | None = None
    fetched_html: str | None = None
    fetched_text: str | None = None
    body_source: str = ""


class VerificationService:
    def __init__(
        self,
        session: Session,
        *,
        llm: StructuredLLMProvider | None = None,
        planner_llm: StructuredLLMProvider | None = None,
        assessor_llm: StructuredLLMProvider | None = None,
        search: SearchProvider | None = None,
        fetcher: HttpFetcher | None = None,
        extract: Callable[[str, str], str | None] = extract_text,
    ) -> None:
        self.session = session
        self.settings = get_settings()
        self.items = SourceItemRepository(session)
        self.sources = SourceRepository(session)
        self.pipeline = PipelineRunRepository(session)
        self.event_service = EventService(session)
        self.source_service = SourceService(session)
        self.item_service = SourceItemService(session)
        self.llm = llm
        self.planner_llm = planner_llm
        self.assessor_llm = assessor_llm
        self.search = search
        self.fetcher = fetcher or HttpFetcher()
        self.extract = extract

    def verify(self, event_id: UUID, *, trigger: str, context: dict | None = None, claim_id: UUID | None = None) -> dict:
        event = self._load_event(event_id)
        if event is None:
            raise ValueError("event_not_found")
        original_status = event.status

        if self.pipeline.get_running(event_id, VERIFICATION_STAGE) is not None:
            return {
                "skipped": True,
                "reason": "already_running",
                "event_id": str(event_id),
                "verified": 0,
            }

        run = PipelineRun(
            event_id=event.id,
            stage=VERIFICATION_STAGE,
            status=PipelineStatus.RUNNING,
            metadata_json={"trigger": trigger, "context": context or {}, "target_claim_id": str(claim_id) if claim_id else None},
        )
        self.pipeline.add(run)
        try:
            with self.session.begin_nested():
                self.session.flush()
        except IntegrityError:
            self.session.expunge(run)
            return {
                "skipped": True,
                "reason": "already_running",
                "event_id": str(event_id),
                "verified": 0,
            }

        try:
            with usage_scope(
                stage=VERIFICATION_STAGE,
                event_id=event.id,
                pipeline_run_id=run.id,
            ):
                result = postgres_safe_json(self._run(event, claim_id=claim_id) if claim_id else self._run(event))
            run.status = PipelineStatus.SUCCESS
            run.finished_at = utc_now()
            run.metadata_json = postgres_safe_json({**(run.metadata_json or {}), **result})
            event.status = original_status
            self.session.flush()
            return {"skipped": False, "event_id": str(event.id), **result}
        except ProviderNotConfiguredError as exc:
            return self._fail(run, event, original_status, str(exc))
        except Exception as exc:
            try:
                return self._fail(run, event, original_status, str(exc))
            except Exception:
                self.session.rollback()
                return {
                    "skipped": False,
                    "event_id": str(event.id),
                    "verified": 0,
                    "error": str(exc),
                }

    def _fail(self, run: PipelineRun, event: Event, original_status: Any, message: str) -> dict:
        run.status = PipelineStatus.FAILED
        run.error_message = message
        run.finished_at = utc_now()
        event.status = original_status
        self.session.flush()
        return {
            "skipped": False,
            "event_id": str(event.id),
            "verified": 0,
            "error": message,
        }

    def _load_event(self, event_id: UUID) -> Event | None:
        stmt = (
            select(Event)
            .execution_options(populate_existing=True)
            .options(
                selectinload(Event.event_sources)
                .selectinload(EventSource.source_item)
                .selectinload(SourceItem.source),
                selectinload(Event.claims)
                .selectinload(Claim.evidence)
                .selectinload(ClaimEvidence.source_item)
                .selectinload(SourceItem.source),
            )
            .where(Event.id == event_id)
        )
        return self.session.scalars(stmt).first()

    def _flagged_ids(self, event_id: UUID) -> tuple[set[UUID], list[dict]]:
        consumed: list[dict] = []
        flagged: set[UUID] = set()
        for run in self.pipeline.list_for_event(event_id, limit=30):
            if run.stage != CLAIM_STAGE or run.status != PipelineStatus.SUCCESS:
                continue
            raw = (run.metadata_json or {}).get("needs_external_verification") or []
            for row in raw:
                if not isinstance(row, dict) or not row.get("claim_id"):
                    continue
                consumed.append(row)
                flagged.add(UUID(str(row["claim_id"])))
            break
        return flagged, consumed

    def _cheap_provider(self, injected: StructuredLLMProvider | None) -> StructuredLLMProvider | None:
        if injected is not None:
            return injected
        if self.llm is not None:
            return None
        return get_structured_provider_optional(ModelRole.ULTRA_LIGHT_PROCESSING)

    def _run(self, event: Event, *, claim_id: UUID | None = None) -> dict:
        targeted = claim_id is not None
        flagged, consumed = self._flagged_ids(event.id)
        claim_run = latest_success_claim_resolution(self.session, event.id)
        claim_meta = (claim_run.metadata_json if claim_run is not None else None) or {}
        coverage = None
        raw_coverage = claim_meta.get("coverage")
        if isinstance(raw_coverage, dict):
            try:
                coverage = CoverageContract.model_validate(raw_coverage)
            except Exception:
                coverage = None
        centrals = central_claim_ids(coverage) if coverage is not None else set()
        selected, skipped_policy = select_claims(
            list(event.claims),
            flagged_ids=flagged,
            limit=self.settings.max_verification_claims_per_event,
            central_ids=centrals,
        )
        if claim_id is not None:
            target = next((claim for claim in event.claims if claim.id == claim_id), None)
            if target is None:
                raise ValueError("claim_not_in_event")
            selected = [SelectedClaim(target, ["explicit_recheck"])]
            skipped_policy = [{"claim_id": str(c.id), "reason": "outside_recheck"} for c in event.claims if c.id != claim_id]
        deferred = [row for row in skipped_policy if row.get("reason") == "budget"]
        budget = VerificationBudget(
            limit=self.settings.max_verification_claims_per_event,
            selected_ids=[str(row.claim.id) for row in selected],
            deferred=deferred,
            central_unverified=[
                str(cid)
                for cid in centrals
                if str(cid) not in {str(row.claim.id) for row in selected}
            ],
        )
        fingerprint = claim_meta.get("claims_fingerprint") or claims_fingerprint(list(event.claims))
        payload: dict[str, Any] = {
            "contract_version": CONTRACT_VERSION,
            "comparison_policy_version": COMPARISON_POLICY_VERSION,
            "input_evidence": {},
            "model_results": {},
            "packets": {},
            "comparison_checks": {},
            "claims_fingerprint": fingerprint,
            "based_on_claim_run_id": str(claim_run.id) if claim_run is not None else None,
            "coverage": coverage.model_dump(mode="json") if coverage is not None else None,
            "verification_budget": budget.model_dump(mode="json"),
            "verification_incomplete": bool(budget.central_unverified),
            "selected": [{"claim_id": str(row.claim.id), "reasons": row.reasons} for row in selected],
            "skipped_policy": skipped_policy,
            "consumed_needs_external_verification": consumed,
            "queries": {},
            "plans": {},
            "temporal_scope": {},
            "freshness": {},
            "primary_found": {},
            "primary_source_found": {},
            "primary_source_supports_claim": {},
            "escalated": {},
            "assessments": {},
            "skipped_search": [],
            "sol": [],
            "decision_by_claim_id": {},
            "attached": 0,
            "fetched": 0,
            "cited": 0,
            "verified": 0,
            "search_unavailable": False,
        }
        if coverage is not None:
            coverage.verification_incomplete = bool(budget.central_unverified)
            payload["coverage"] = coverage.model_dump(mode="json")
        if not selected:
            payload["evaluated_claims"] = [
                row.model_dump(mode="json") for row in evaluated_claims_payload(list(event.claims))
            ]
            return payload

        search = self.search or get_search_provider()
        sol_prompt = load_prompt("verification.md")
        ordered = sorted(
            selected,
            key=lambda row: 1 if is_numeric_comparison_claim(row.claim) else 0,
        )

        for row in ordered:
            claim = row.claim
            status_before = claim.status
            claim_id = str(claim.id)
            self._comparison_checks = []
            payload["input_evidence"][claim_id] = [
                {"source_item_id": str(ev.source_item_id), "evidence_type": ev.evidence_type.value,
                 "excerpt": ev.excerpt, "confidence": ev.confidence} for ev in claim.evidence
            ]
            plan = self._plan_for(claim, event)
            preferred = preferred_domains(
                plan.jurisdiction,
                plan.verification_target.value,
                plan.subject.value,
                province=event.province,
                judicial_forum=plan.judicial_forum.value,
                claim_text=claim.canonical_text,
            )
            payload["plans"][claim_id] = plan.model_dump(mode="json")
            payload["temporal_scope"][claim_id] = plan.temporal_scope.value
            comparison_status = try_resolve_numeric_comparison(claim, list(event.claims))
            if comparison_status is not None:
                claim.status = comparison_status
                payload["skipped_search"].append(claim_id)
                payload["escalated"][claim_id] = False
                payload["primary_found"][claim_id] = False
                payload["primary_source_found"][claim_id] = False
                payload["primary_source_supports_claim"][claim_id] = False
                payload["verified"] += 1
                continue
            if skip_directed_search(claim, plan, preferred):
                found = claim_has_preferred_evidence(claim, preferred)
                authentic = self._utterance_primary_supports(claim)
                payload["skipped_search"].append(claim_id)
                payload["escalated"][claim_id] = False
                payload["primary_found"][claim_id] = found or authentic
                payload["primary_source_found"][claim_id] = found or authentic
                payload["primary_source_supports_claim"][claim_id] = found or authentic
                self._record_decision(
                    payload,
                    claim,
                    plan,
                    status_before=status_before,
                    llm_reason="skipped_search",
                    unresolved=False,
                    escalated=False,
                    primary_found=found or authentic,
                    primary_supports=found or authentic,
                    packet_size=len(claim.evidence),
                )
                continue

            queries = build_verification_searches(
                claim,
                plan,
                preferred,
                limit=self.settings.max_verification_queries_per_claim,
                count=self.settings.max_verification_results_per_query,
            )
            window = search_window_for(plan, claim)
            payload["queries"][claim_id] = [query.text for query in queries]
            payload["freshness"][claim_id] = window.freshness
            hits = self._collect_hits(search, queries, plan, window.freshness, window.since, window.until)
            if getattr(self, "_search_unavailable", False):
                payload["search_unavailable"] = True
            payload.setdefault("search_requests", {})[claim_id] = self._search_requests
            packet, fetched = self._packet_for(claim, hits)
            payload["packets"][claim_id] = [
                {"source_ref": src.ref, "url": src.url, "title": src.title,
                 "snippet": src.snippet, "body_source": src.body_source} for src in packet
            ]
            payload["fetched"] += fetched
            assessment = self._assess(event, claim, packet, plan)
            primary_found = any(is_preferred_domain(src.url, preferred) for src in packet)
            primary_supports = False
            if assessment is not None:
                payload["assessments"][claim_id] = assessment.model_dump(mode="json")
                attached, cited, primary_supports = self._apply_judgements(
                    event, claim, packet, assessment, preferred
                )
                payload["attached"] += attached
                payload["cited"] += cited
            if self._utterance_primary_supports(claim):
                primary_supports = True
            payload["primary_found"][claim_id] = bool(primary_found)
            payload["primary_source_found"][claim_id] = bool(primary_found)
            payload["primary_source_supports_claim"][claim_id] = bool(primary_supports)
            escalate = needs_sol_after_assessment(
                claim, plan, assessment, primary_support=bool(primary_supports)
            )
            if targeted:
                escalate = True
            payload["escalated"][claim_id] = escalate
            payload["verified"] += 1
            if escalate:
                llm = self.llm or get_structured_provider(ModelRole.VERIFICATION)
                result = llm.generate_structured(
                    system_prompt=sol_prompt,
                    user_prompt=self._user_prompt(event, claim, packet, plan),
                    schema=VerificationResult,
                )
                payload["model_results"][claim_id] = result.model_dump(mode="json")
                attached, cited, primary_supports, decision = self._apply_result(
                    event, claim, packet, result, plan, preferred, bool(primary_supports)
                )
                payload["attached"] += attached
                payload["cited"] += cited
                payload["primary_source_supports_claim"][claim_id] = bool(primary_supports)
                payload["sol"].append(
                    {
                        "claim_id": claim_id,
                        "status_before": status_before.value,
                        "status_after": claim.status.value,
                        "unresolved": decision.unresolved,
                        "reason": decision.final_reason,
                        "llm_reason": decision.llm_reason,
                        "escalated": True,
                    }
                )
                payload["decision_by_claim_id"][claim_id] = decision.model_dump(mode="json")
                payload["comparison_checks"][claim_id] = self._comparison_checks
                continue
            if assessment is not None and assessment_has_support(assessment):
                claim.status = apply_primary_requirement(
                    claim, ClaimStatus.SUPPORTED, plan, primary_supports=bool(primary_supports)
                )
            decision = self._decision_after_policy(
                claim,
                plan,
                desired=ClaimStatus.SUPPORTED if assessment is not None and assessment_has_support(assessment) else claim.status,
                llm_reason=(assessment.reason if assessment is not None else None) or "cheap_assessment",
                unresolved=False,
                primary_found=bool(primary_found),
                primary_supports=bool(primary_supports),
                packet_size=len(packet),
            )
            payload["sol"].append(
                {
                    "claim_id": claim_id,
                    "status_before": status_before.value,
                    "status_after": claim.status.value,
                    "unresolved": decision.unresolved,
                    "reason": decision.final_reason,
                    "llm_reason": decision.llm_reason,
                    "escalated": False,
                }
            )
            payload["decision_by_claim_id"][claim_id] = decision.model_dump(mode="json")
            payload["comparison_checks"][claim_id] = self._comparison_checks
        if not targeted:
            self._reconcile_verified_competitors(list(event.claims), payload)
        payload["evaluated_claims"] = [row.model_dump(mode="json") for row in evaluated_claims_payload(list(event.claims))]
        return payload

    def _reconcile_verified_competitors(self, claims: list[Claim], payload: dict[str, Any]) -> None:
        view = view_from_mapping(payload)
        groups: dict[str, list[Claim]] = defaultdict(list)
        for claim in claims:
            groups[comparison_key_for(claim)].append(claim)
        winners = [
            claim
            for claim in claims
            if claim.status == ClaimStatus.SUPPORTED and is_strong_verification(claim.id, view, claim=claim)
        ]
        for winner in winners:
            if not _has_structured_spo(winner):
                continue
            for sibling in groups[comparison_key_for(winner)]:
                if sibling.id == winner.id:
                    continue
                if assertion_key_for(sibling) == assertion_key_for(winner):
                    continue
                if is_utterance_claim(sibling) or is_utterance_claim(winner):
                    continue
                if not _has_structured_spo(sibling):
                    continue
                if sibling.status == ClaimStatus.OUTDATED:
                    continue
                if sibling.status == ClaimStatus.SUPPORTED and is_strong_verification(sibling.id, view, claim=sibling):
                    continue
                if not any(row.evidence_type == EvidenceType.SUPPORTS for row in sibling.evidence):
                    continue
                if not _same_temporal_context(winner, sibling):
                    continue
                # A different supported assertion is not a grounded refutation of
                # its sibling. Each DISPROVEN needs its own admitted contradiction.
                sibling.status = ClaimStatus.CONFLICTING

    def _plan_for(self, claim: Claim, event: Event) -> VerificationPlan:
        fallback = heuristic_plan(claim, jurisdiction=self.settings.editorial_country_code)
        if is_regulatory_count(claim):
            # Category and full material query are already explicit in the claim.
            return fallback
        provider = self._cheap_provider(self.planner_llm)
        if provider is None:
            return fallback
        try:
            planned = provider.generate_structured(
                system_prompt=load_prompt("verification_plan.md"),
                user_prompt=self._plan_prompt(event, claim),
                schema=VerificationPlan,
            )
            return refine_plan(planned, fallback, claim=claim)
        except _PLANNER_ERRORS:
            return fallback

    def _assess(
        self,
        event: Event,
        claim: Claim,
        packet: list[_PacketSource],
        plan: VerificationPlan,
    ) -> CheapClaimEvidenceAssessment | None:
        provider = self._cheap_provider(self.assessor_llm)
        if provider is None or not packet:
            return None
        try:
            return provider.generate_structured(
                system_prompt=load_prompt("claim_evidence_assessment.md"),
                user_prompt=self._user_prompt(event, claim, packet, plan),
                schema=CheapClaimEvidenceAssessment,
            )
        except _PLANNER_ERRORS:
            return None

    def _packet_snippet(self, claim: Claim, item: SourceItem, *, fallback: str | None) -> str:
        body = (item.clean_text or "").strip()
        needles = list(token_set(claim.canonical_text or ""))[:12]
        if body:
            snippet = select_source_snippet(body, budget=SNIPPET_CHARS, extra_needles=needles)
        else:
            snippet = (fallback or item.excerpt or item.title or "")[:SNIPPET_CHARS]
        excerpt = (fallback or "").strip()
        if excerpt and excerpt not in snippet:
            combined = f"{excerpt}\n\n{snippet}".strip()
            snippet = combined[:SNIPPET_CHARS]
        return postgres_safe_text(snippet) or ""

    def _utterance_primary_supports(self, claim: Claim) -> bool:
        role = proposition_role_for(claim)
        if role != PropositionRole.UTTERANCE and canonicalize_claim_type(claim.claim_type) != "declaracion":
            return False
        if is_mixed_proposition(claim.canonical_text or "", claim.claim_type):
            return False
        assessment = assess_origins(claim)
        return assessment.statement_evidence_class == StatementEvidenceClass.AUTHENTIC_PRIMARY

    def _primary_access(self, *, primary_found: bool, primary_supports: bool) -> str:
        if primary_supports:
            return PrimaryAccess.FOUND_RELEVANT.value
        if primary_found:
            return PrimaryAccess.FOUND_UNRELATED.value
        return PrimaryAccess.NOT_FOUND.value

    def _decision_after_policy(
        self,
        claim: Claim,
        plan,
        *,
        desired: ClaimStatus,
        llm_reason: str | None,
        unresolved: bool,
        primary_found: bool,
        primary_supports: bool,
        packet_size: int,
    ) -> ClaimDecision:
        assessment = assess_origins(claim, packet_size=packet_size)
        role = proposition_role_for(claim)
        mixed = is_mixed_proposition(claim.canonical_text or "", claim.claim_type)
        demotion = demotion_for(
            desired_status=desired.value,
            final_status=claim.status.value,
            assessment=assessment,
            primary_required=bool(plan.primary_source_required) if plan is not None else False,
            primary_supports=primary_supports,
            mixed=mixed,
            role=role,
        )
        basis = support_basis_from_assessment(
            claim,
            assessment,
            demotion=demotion,
            evaluated_text=claim.canonical_text,
            primary_access=self._primary_access(primary_found=primary_found, primary_supports=primary_supports),
            status=claim.status.value,
            role=role,
        )
        return ClaimDecision(
            claim_id=str(claim.id),
            status=claim.status.value,
            unresolved=unresolved,
            final_reason=final_reason_for(demotion, assessment, claim.status.value),
            llm_reason=llm_reason,
            support_basis=basis,
            proposition_role=role.value,
        )

    def _record_decision(
        self,
        payload: dict[str, Any],
        claim: Claim,
        plan,
        *,
        status_before: ClaimStatus,
        llm_reason: str | None,
        unresolved: bool,
        escalated: bool,
        primary_found: bool,
        primary_supports: bool,
        packet_size: int,
    ) -> ClaimDecision:
        decision = self._decision_after_policy(
            claim,
            plan,
            desired=claim.status,
            llm_reason=llm_reason,
            unresolved=unresolved,
            primary_found=primary_found,
            primary_supports=primary_supports,
            packet_size=packet_size,
        )
        payload["sol"].append(
            {
                "claim_id": str(claim.id),
                "status_before": status_before.value,
                "status_after": claim.status.value,
                "unresolved": decision.unresolved,
                "reason": decision.final_reason,
                "llm_reason": decision.llm_reason,
                "escalated": escalated,
            }
        )
        payload["decision_by_claim_id"][str(claim.id)] = decision.model_dump(mode="json")
        return decision

    def _plan_prompt(self, event: Event, claim: Claim) -> str:
        occurred = claim.occurred_at.isoformat() if claim.occurred_at else ""
        when = event.started_at or event.detected_at
        return "\n".join(
            [
                f"Suceso (contexto mínimo, no uses su fecha para la temporalidad del Claim): {event.title_internal}",
                f"Detectado/inicio: {when}",
                f"Lugar del suceso (no lo uses para foro judicial si el Claim no lo menciona): "
                f"{event.locality or ''} {event.province or ''}".strip(),
                f"canonical_text={claim.canonical_text}",
                f"claim_type={canonicalize_claim_type(claim.claim_type)}",
                f"importance={claim.importance.value} status={claim.status.value}",
                f"occurred_at={occurred}",
                f"subject={claim.subject or ''} predicate={claim.predicate or ''} "
                f"object_text={claim.object_text or ''} normalized_value={claim.normalized_value or ''} "
                f"unit={claim.unit or ''}",
            ]
        )

    def _collect_hits(
        self,
        search: SearchProvider,
        queries: list[SearchQuery],
        plan: VerificationPlan,
        freshness: str | None,
        since,
        until,
    ) -> list[SearchHit]:
        official = [query for query in queries if query.include_domains]
        general = [query for query in queries if not query.include_domains]
        self._search_requests = []
        self._search_unavailable = False
        hits: list[SearchHit] = []
        seen: set[str] = set()

        def _run(requests: list[SearchQuery]) -> int:
            added = 0
            for query in requests:
                self._search_requests.append(query.model_dump(mode="json"))
                try:
                    found = search.search(query)
                except Exception as exc:
                    if not is_transient_http_error(exc):
                        raise
                    self._search_unavailable = True
                    found = []
                for hit in found:
                    if not hit.url:
                        continue
                    canonical = canonicalize_url(hit.url) or hit.url
                    if canonical in seen:
                        continue
                    seen.add(canonical)
                    hits.append(hit)
                    added += 1
            return added

        official_added = _run(official) if official else 0
        utterance = (
            plan.verification_target.value == "PRIMARY_STATEMENT"
            or plan.subject.value == "PUBLIC_STATEMENT"
            or plan.independent_corroboration_required
        )
        need_general = (not official) or official_added == 0 or utterance
        if need_general and general:
            _run(general)
        return hits

    def _packet_for(self, claim: Claim, hits: list[SearchHit]) -> tuple[list[_PacketSource], int]:
        packet: list[_PacketSource] = []
        seen: set[str] = set()
        ref = 1
        for row in claim.evidence:
            item = row.source_item
            if item is None:
                continue
            canonical = canonicalize_url(item.canonical_url or item.url)
            if canonical:
                seen.add(canonical)
            snippet = self._packet_snippet(claim, item, fallback=row.excerpt or item.excerpt)
            packet.append(
                _PacketSource(
                    ref=ref,
                    url=item.url,
                    title=item.title or "",
                    snippet=snippet,
                    item=item,
                    body_source=usable_body_source(item),
                )
            )
            ref += 1

        fetched = 0
        for hit in hits:
            if not hit.url:
                continue
            canonical = canonicalize_url(hit.url)
            if not canonical or canonical in seen:
                continue
            seen.add(canonical)
            existing = self.items.get_by_canonical_url(canonical) or self.items.get_by_canonical_url(hit.url)
            if existing is not None:
                snippet = self._packet_snippet(claim, existing, fallback=hit.snippet or existing.excerpt)
                packet.append(
                    _PacketSource(
                        ref=ref,
                        url=existing.url,
                        title=existing.title or hit.title,
                        snippet=snippet,
                        item=existing,
                        hit=hit,
                        body_source=usable_body_source(existing),
                    )
                )
                ref += 1
                continue
            html, text = self._fetch_to_memory(hit.url)
            if html is not None:
                fetched += 1
            body_source = BODY_SOURCE_EXTRACTED_HTML if text else BODY_SOURCE_SEARCH_SNIPPET
            snippet_source = text or hit.snippet or hit.title or ""
            snippet = postgres_safe_text(
                select_source_snippet(
                    snippet_source,
                    budget=SNIPPET_CHARS,
                    extra_needles=list(token_set(claim.canonical_text or ""))[:12],
                )
                or snippet_source[:SNIPPET_CHARS]
            ) or ""
            packet.append(
                _PacketSource(
                    ref=ref,
                    url=hit.url,
                    title=hit.title,
                    snippet=snippet,
                    hit=hit,
                    fetched_html=html,
                    fetched_text=text,
                    body_source=body_source if html else BODY_SOURCE_SEARCH_SNIPPET,
                )
            )
            ref += 1
        return packet, fetched

    def _fetch_to_memory(self, url: str) -> tuple[str | None, str | None]:
        try:
            fetched = self.fetcher.fetch(url)
        except Exception:
            return None, None
        html = fetched.body or ""
        content_type = getattr(fetched, "content_type", "") or ""
        if not html or not is_extractable_document(fetched.url or url, content_type, html):
            return None, None
        text = self.extract(html, fetched.url or url)
        return html, text

    def _user_prompt(
        self,
        event: Event,
        claim: Claim,
        packet: list[_PacketSource],
        plan: VerificationPlan | None = None,
    ) -> str:
        kind = canonicalize_claim_type(claim.claim_type)
        occurred = claim.occurred_at.isoformat() if claim.occurred_at else ""
        lines = [
            "Claim a evaluar (única proposición; no la sustituyas por el título del suceso):",
            f"canonical_text={claim.canonical_text}",
            f"claim_type={kind} status_actual={claim.status.value} importance={claim.importance.value}",
            f"subject={claim.subject or ''} predicate={claim.predicate or ''} "
            f"object_text={claim.object_text or ''} normalized_value={claim.normalized_value or ''} "
            f"unit={claim.unit or ''} occurred_at={occurred}",
            "Atribución: las fuentes listadas documentan cómo conocemos el dicho; "
            "sus datos económicos no verifican por sí solos lo que dijo un medio.",
            f"Suceso (contexto mínimo; no juzgues esta frase en lugar del Claim): {event.title_internal} ({event.event_type})",
            f"Lugar: {event.locality or ''} {event.province or ''}".strip(),
        ]
        if plan is not None:
            lines.append(f"VerificationPlan={plan.model_dump_json()}")
        lines.append("Fuentes (source_ref 1..N, snippet truncado; no hay HTML crudo ni el Event entero):")
        for src in packet:
            lines.append(
                f"{src.ref}. title={src.title} url={src.url} body_source={src.body_source or 'unknown'} "
                f"published_at={src.item.published_at if src.item else None}\n"
                f"snippet={src.snippet}"
            )
        return "\n".join(lines)

    def _apply_judgements(
        self,
        event: Event,
        claim: Claim,
        packet: list[_PacketSource],
        assessment: CheapClaimEvidenceAssessment,
        preferred: list[str],
    ) -> tuple[int, int, bool]:
        attached = 0
        cited = 0
        primary_support = False
        by_ref = {src.ref: src for src in packet}
        for row in assessment.judgements:
            selected_type = PERSISTABLE_JUDGEMENTS.get(row.relation)
            if selected_type is None:
                continue
            evidence_type, _ = self._admit_relation(claim, by_ref.get(row.source_ref), row, selected_type)
            added, counted = self._attach_evidence(
                event, claim, by_ref, row.source_ref, evidence_type, row, selected_type=selected_type
            )
            attached += added
            cited += counted
            src = by_ref.get(row.source_ref)
            if (
                counted
                and evidence_type == EvidenceType.SUPPORTS
                and src is not None
                and is_preferred_domain(src.url, preferred)
            ):
                primary_support = True
        self.session.flush()
        return attached, cited, self._primary_support_from_packet(claim, packet, preferred)

    def _apply_result(
        self,
        event: Event,
        claim: Claim,
        packet: list[_PacketSource],
        result: VerificationResult,
        plan: VerificationPlan,
        preferred: list[str],
        primary_supports: bool,
    ) -> tuple[int, int, bool, ClaimDecision]:
        by_ref = {src.ref: src for src in packet}
        attached = 0
        cited = 0
        valid_contradictions = set()
        for row in result.evidence:
            evidence_type, valid = self._admit_relation(claim, by_ref.get(row.source_ref), row, row.evidence_type)
            added, counted = self._attach_evidence(
                event,
                claim,
                by_ref,
                row.source_ref,
                evidence_type,
                row,
                selected_type=row.evidence_type,
            )
            if counted and valid:
                valid_contradictions.add(by_ref[row.source_ref].item.id)
            attached += added
            cited += counted
            src = by_ref.get(row.source_ref)
            if (
                counted
                and evidence_type == EvidenceType.SUPPORTS
                and src is not None
                and is_preferred_domain(src.url, preferred)
            ):
                primary_supports = True

        self.session.flush()
        # Previous runs remain in metadata. A historical CONTRADICTS cannot
        # survive a new evaluation without a current, admitted comparison.
        for ev in claim.evidence:
            if ev.evidence_type == EvidenceType.CONTRADICTS and ev.source_item_id not in valid_contradictions:
                ev.evidence_type = EvidenceType.MENTIONS
        primary_supports = self._primary_support_from_packet(claim, packet, preferred)
        if self._utterance_primary_supports(claim):
            primary_supports = True
        unresolved = False
        desired = result.status
        rejected_disproof = desired == ClaimStatus.DISPROVEN and not valid_contradictions
        if rejected_disproof:
            has_support = any(ev.evidence_type == EvidenceType.SUPPORTS for ev in claim.evidence)
            claim.status = ClaimStatus.SINGLE_SOURCE if has_support else ClaimStatus.UNCERTAIN
            unresolved = not has_support
        elif result.unresolved and result.status in {ClaimStatus.CONFLICTING, ClaimStatus.UNCERTAIN}:
            claim.status = result.status
            unresolved = True
        else:
            claim.status = apply_primary_requirement(
                claim, result.status, plan, primary_supports=primary_supports
            )
            unresolved = False
        decision = self._decision_after_policy(
            claim,
            plan,
            desired=desired,
            llm_reason=result.reason,
            unresolved=unresolved,
            primary_found=any(is_preferred_domain(src.url, preferred) for src in packet),
            primary_supports=primary_supports,
            packet_size=len(packet),
        )
        if rejected_disproof:
            decision.final_reason = "No se acreditó una contradicción pertinente y comparable de la proposición evaluada."
        elif claim.status == ClaimStatus.DISPROVEN:
            decision.final_reason = "Una contradicción con correspondencia comprobada de proposición y contexto refuta el claim."
        return attached, cited, primary_supports, decision

    def _primary_support_from_packet(self, claim, packet, preferred):
        supports = {ev.source_item_id: ev for ev in claim.evidence if ev.evidence_type == EvidenceType.SUPPORTS}
        checks = {row["source_ref"]: row for row in getattr(self, "_comparison_checks", [])}
        for src in packet:
            if not src.item or src.item.id not in supports or not is_preferred_domain(src.url, preferred):
                continue
            ev = supports[src.item.id]
            if is_regulatory_count(claim):
                if src.body_source != "extracted_html" or not ev.excerpt or not excerpt_in_source(ev.excerpt, src.item.clean_text):
                    continue
                check = checks.get(src.ref, {})
                if check.get("admitted") != "SUPPORTS" or check.get("reason") != "comparable_count_support":
                    continue
            return True
        return False

    def _admit_relation(self, claim, src, row, relation):
        valid = False
        reason = "semantic_assessment"
        original = relation
        if relation == EvidenceType.CONTRADICTS:
            body = (src.item.clean_text if src and src.item else src.fetched_text if src else "") or ""
            valid, reason = valid_contradiction(claim, getattr(row, "comparison", None),
                                                body=body, body_source=src.body_source if src else "")
            if valid and not excerpt_in_source(row.comparison.evidence_fragment, getattr(row, "excerpt", None)):
                valid, reason = False, "comparison_not_in_cited_excerpt"
            if not valid:
                relation = EvidenceType.QUALIFIES if reason in {"compatible_rounding", "same_value"} else EvidenceType.MENTIONS
        elif relation == EvidenceType.SUPPORTS:
            excerpt = getattr(row, "excerpt", None) or ""
            if (attributed_statement(claim.canonical_text) or claim.claim_type == "declaracion") and not attributed_statement(excerpt):
                relation, reason = EvidenceType.MENTIONS, "statement_not_established"
            elif temporal_comparison(claim.canonical_text) and not temporal_comparison(excerpt):
                relation, reason = EvidenceType.QUALIFIES, "trajectory_only_partially_established"
            elif is_regulatory_count(claim) and not attributed_statement(excerpt):
                from app.services.evidence_comparison import valid_count_support
                body = (src.item.clean_text if src and src.item else src.fetched_text if src else "") or ""
                supported, reason = valid_count_support(claim, getattr(row, "comparison", None),
                                                       body=body, body_source=src.body_source if src else "")
                if supported and not excerpt_in_source(row.comparison.evidence_fragment, excerpt):
                    supported, reason = False, "comparison_not_in_cited_excerpt"
                if not supported:
                    relation = EvidenceType.QUALIFIES
        if not hasattr(self, "_comparison_checks"):
            self._comparison_checks = []
        self._comparison_checks.append({"source_ref": row.source_ref, "requested": original.value,
                                        "admitted": relation.value, "valid_contradiction": valid, "reason": reason})
        return relation, valid

    def _attach_evidence(
        self,
        event: Event,
        claim: Claim,
        by_ref: dict[int, _PacketSource],
        source_ref: int,
        evidence_type: EvidenceType,
        row: VerificationResult | CheapEvidenceJudgement | Any,
        *,
        selected_type: EvidenceType | None = None,
    ) -> tuple[int, int]:
        src = by_ref.get(source_ref)
        if src is None:
            return 0, 0
        item = self._materialize_cited(src)
        if item is None:
            return 0, 0
        excerpt = (getattr(row, "excerpt", None) or "").strip() or None
        if excerpt and not excerpt_in_source(
            excerpt, item.clean_text, item.excerpt, item.title, src.snippet
        ):
            return 0, 0
        existing = next((ev for ev in claim.evidence if ev.source_item_id == item.id), None)
        if existing is None:
            existing = self.session.scalars(
                select(ClaimEvidence).where(
                    ClaimEvidence.claim_id == claim.id,
                    ClaimEvidence.source_item_id == item.id,
                )
            ).first()
            if existing is not None:
                claim.evidence.append(existing)
        if existing is not None:
            # Verification supersedes the earlier assessment; numeric priority
            # must not make an erroneous contradiction irreversible.
            existing.evidence_type = evidence_type
            if excerpt:
                existing.excerpt = excerpt
            confidence = getattr(row, "confidence", None)
            if confidence is not None:
                existing.confidence = confidence
            if item.url:
                existing.source_url = item.url
            return 0, 1
        evidence = ClaimEvidence(
            claim_id=claim.id,
            source_item_id=item.id,
            evidence_type=evidence_type,
            excerpt=excerpt,
            source_url=item.url,
            confidence=getattr(row, "confidence", None),
        )
        self.session.add(evidence)
        claim.evidence.append(evidence)
        if (selected_type or evidence_type) not in EVENT_SOURCE_EVIDENCE_TYPES:
            return 0, 1
        _, created_link = self.event_service.attach_source(
            event,
            item.id,
            relation_type=EventSourceRelation.ADDITIONAL,
            is_primary=False,
        )
        return (1 if created_link else 0), 1

    def _materialize_cited(self, src: _PacketSource) -> SourceItem | None:
        if src.item is not None:
            return src.item
        url = src.url
        canonical = canonicalize_url(url)
        existing = self.items.get_by_canonical_url(canonical) or self.items.get_by_canonical_url(url)
        if existing is not None:
            src.item = existing
            return existing
        html = postgres_safe_text(src.fetched_html or "") or ""
        text = postgres_safe_text(src.fetched_text or src.snippet)
        if not html and not text:
            return None
        domain = url_domain(canonical)
        source = self._source_for_domain(domain, canonical or url)
        fingerprint = content_fingerprint(title=src.title, body=text)
        snippet = src.hit.snippet if src.hit is not None else text
        outcome = self.item_service.ingest(
            SourceItemCreate(
                source_id=source.id,
                url=url,
                canonical_url=canonical,
                content_hash=fingerprint,
                title=src.title or None,
                raw_text=html[:20000] if html else None,
                clean_text=text,
                excerpt=(snippet or text or "")[:500] or None,
            )
        )
        if html and is_extracted_body(text, src.title):
            body_source = BODY_SOURCE_EXTRACTED_HTML
        elif is_extracted_body(snippet, src.title):
            body_source = BODY_SOURCE_SEARCH_SNIPPET
        else:
            body_source = BODY_SOURCE_TITLE_ONLY
        if outcome.created or outcome.updated:
            merge_item_metadata(
                outcome.item,
                body_source=body_source,
                fetch_ok=bool(html),
            )
        src.item = outcome.item
        return outcome.item

    def _source_for_domain(self, domain: str, url: str) -> Source:
        existing = self.sources.get_by_domain(domain) if domain else None
        if existing is not None:
            return existing
        return self.source_service.create(
            SourceCreate(
                name=domain or url,
                domain=domain or None,
                homepage_url=f"https://{domain}" if domain else url,
                preferred_ingestion_method=IngestionMethod.UNKNOWN,
                is_monitored=False,
                is_enabled=True,
            )
        )


def _has_structured_spo(claim: Claim) -> bool:
    return bool((claim.subject or "").strip() and (claim.predicate or "").strip())


def _same_temporal_context(left: Claim, right: Claim) -> bool:
    if left.occurred_at is None and right.occurred_at is None:
        return True
    if left.occurred_at is None or right.occurred_at is None:
        return False
    return left.occurred_at == right.occurred_at
