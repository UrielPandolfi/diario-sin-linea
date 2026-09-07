from __future__ import annotations

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
from app.core.text import content_fingerprint, excerpt_in_source, postgres_safe_json, postgres_safe_text
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
    EvidenceJudgementType,
    PERSISTABLE_JUDGEMENTS,
    VerificationPlan,
    VerificationResult,
)
from app.services.claim_service import CLAIM_STAGE
from app.services.event_service import EventService
from app.services.evidence_source_registry import is_preferred_domain, preferred_domains
from app.services.fetching import HttpFetcher, extract_text, is_extractable_document
from app.services.source_item_service import SourceItemService
from app.services.source_service import SourceService
from app.services.verification_plan import (
    apply_primary_requirement,
    assessment_has_support,
    build_verification_queries,
    claim_has_preferred_evidence,
    heuristic_plan,
    is_numeric_comparison_claim,
    needs_sol_after_assessment,
    refine_plan,
    search_window_for,
    skip_directed_search,
    try_resolve_numeric_comparison,
)
from app.services.verification_policy import canonicalize_claim_type, select_claims

VERIFICATION_STAGE = "verification"
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

    def verify(self, event_id: UUID, *, trigger: str, context: dict | None = None) -> dict:
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
            metadata_json={"trigger": trigger, "context": context or {}},
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
                result = postgres_safe_json(self._run(event))
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

    def _run(self, event: Event) -> dict:
        flagged, consumed = self._flagged_ids(event.id)
        selected, skipped_policy = select_claims(
            list(event.claims),
            flagged_ids=flagged,
            limit=self.settings.max_verification_claims_per_event,
        )
        payload: dict[str, Any] = {
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
            "attached": 0,
            "fetched": 0,
            "cited": 0,
            "verified": 0,
        }
        if not selected:
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
                payload["skipped_search"].append(claim_id)
                payload["escalated"][claim_id] = False
                payload["primary_found"][claim_id] = found
                payload["primary_source_found"][claim_id] = found
                payload["primary_source_supports_claim"][claim_id] = found
                continue

            queries = build_verification_queries(
                claim,
                plan,
                preferred,
                limit=self.settings.max_verification_queries_per_claim,
            )
            window = search_window_for(plan, claim)
            payload["queries"][claim_id] = queries
            payload["freshness"][claim_id] = window.freshness
            hits = self._collect_hits(search, queries, plan, window.freshness, window.since, window.until)
            packet, fetched = self._packet_for(claim, hits)
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
            payload["primary_found"][claim_id] = bool(primary_found)
            payload["primary_source_found"][claim_id] = bool(primary_found)
            payload["primary_source_supports_claim"][claim_id] = bool(primary_supports)
            escalate = needs_sol_after_assessment(
                claim, plan, assessment, primary_support=bool(primary_supports)
            )
            payload["escalated"][claim_id] = escalate
            payload["verified"] += 1
            if escalate:
                llm = self.llm or get_structured_provider(ModelRole.VERIFICATION)
                result = llm.generate_structured(
                    system_prompt=sol_prompt,
                    user_prompt=self._user_prompt(event, claim, packet, plan),
                    schema=VerificationResult,
                )
                attached, cited, primary_supports = self._apply_result(
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
                        "unresolved": result.unresolved,
                        "reason": result.reason,
                        "escalated": True,
                    }
                )
                continue
            if assessment is not None and assessment_has_support(assessment):
                claim.status = apply_primary_requirement(
                    claim, ClaimStatus.SUPPORTED, plan, primary_supports=bool(primary_supports)
                )
            payload["sol"].append(
                {
                    "claim_id": claim_id,
                    "status_before": status_before.value,
                    "status_after": claim.status.value,
                    "unresolved": False,
                    "reason": (assessment.reason if assessment is not None else None) or "cheap_assessment",
                    "escalated": False,
                }
            )
        return payload

    def _plan_for(self, claim: Claim, event: Event) -> VerificationPlan:
        fallback = heuristic_plan(claim, jurisdiction=self.settings.editorial_country_code)
        provider = self._cheap_provider(self.planner_llm)
        if provider is None:
            return fallback
        try:
            planned = provider.generate_structured(
                system_prompt=load_prompt("verification_plan.md"),
                user_prompt=self._plan_prompt(event, claim),
                schema=VerificationPlan,
            )
            return refine_plan(planned, fallback)
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
        queries: list[str],
        plan: VerificationPlan,
        freshness: str | None,
        since,
        until,
    ) -> list[SearchHit]:
        official = [text for text in queries if "site:" in text.lower()]
        general = [text for text in queries if "site:" not in text.lower()]
        hits: list[SearchHit] = []
        seen: set[str] = set()
        per_query = self.settings.max_verification_results_per_query

        def _run(texts: list[str]) -> int:
            added = 0
            for text in texts:
                for hit in search.search(
                    SearchQuery(text=text, count=per_query, freshness=freshness, since=since, until=until)
                ):
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
        need_general = (not official) or official_added == 0 or plan.independent_corroboration_required
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
            snippet = postgres_safe_text(
                (row.excerpt or item.excerpt or item.clean_text or item.title or "")[:SNIPPET_CHARS]
            ) or ""
            packet.append(
                _PacketSource(ref=ref, url=item.url, title=item.title or "", snippet=snippet, item=item)
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
                snippet = postgres_safe_text(
                    (existing.excerpt or existing.clean_text or hit.snippet or existing.title or "")[:SNIPPET_CHARS]
                ) or ""
                packet.append(
                    _PacketSource(
                        ref=ref,
                        url=existing.url,
                        title=existing.title or hit.title,
                        snippet=snippet,
                        item=existing,
                        hit=hit,
                    )
                )
                ref += 1
                continue
            html, text = self._fetch_to_memory(hit.url)
            if html is not None:
                fetched += 1
            snippet = (text or hit.snippet or hit.title or "")[:SNIPPET_CHARS]
            packet.append(
                _PacketSource(
                    ref=ref,
                    url=hit.url,
                    title=hit.title,
                    snippet=postgres_safe_text(snippet) or "",
                    hit=hit,
                    fetched_html=html,
                    fetched_text=text,
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
            f"Suceso (contexto mínimo): {event.title_internal} ({event.event_type})",
            f"Lugar: {event.locality or ''} {event.province or ''}".strip(),
            "Claim:",
            f"canonical_text={claim.canonical_text}",
            f"claim_type={kind} status_actual={claim.status.value} importance={claim.importance.value}",
            f"subject={claim.subject or ''} predicate={claim.predicate or ''} "
            f"object_text={claim.object_text or ''} normalized_value={claim.normalized_value or ''} "
            f"unit={claim.unit or ''} occurred_at={occurred}",
        ]
        if plan is not None:
            lines.append(f"VerificationPlan={plan.model_dump_json()}")
        lines.append("Fuentes (source_ref 1..N, snippet truncado; no hay HTML crudo ni el Event entero):")
        for src in packet:
            lines.append(f"{src.ref}. title={src.title} url={src.url}\nsnippet={src.snippet}")
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
            evidence_type = PERSISTABLE_JUDGEMENTS.get(row.relation)
            if evidence_type is None:
                continue
            added, counted = self._attach_evidence(event, claim, by_ref, row.source_ref, evidence_type, row)
            attached += added
            cited += counted
            src = by_ref.get(row.source_ref)
            if (
                counted
                and row.relation == EvidenceJudgementType.SUPPORTS
                and src is not None
                and is_preferred_domain(src.url, preferred)
            ):
                primary_support = True
        self.session.flush()
        return attached, cited, primary_support

    def _apply_result(
        self,
        event: Event,
        claim: Claim,
        packet: list[_PacketSource],
        result: VerificationResult,
        plan: VerificationPlan,
        preferred: list[str],
        primary_supports: bool,
    ) -> tuple[int, int, bool]:
        by_ref = {src.ref: src for src in packet}
        attached = 0
        cited = 0
        for row in result.evidence:
            added, counted = self._attach_evidence(
                event, claim, by_ref, row.source_ref, row.evidence_type, row
            )
            attached += added
            cited += counted
            src = by_ref.get(row.source_ref)
            if (
                counted
                and row.evidence_type == EvidenceType.SUPPORTS
                and src is not None
                and is_preferred_domain(src.url, preferred)
            ):
                primary_supports = True

        self.session.flush()
        if result.unresolved:
            if result.status in {ClaimStatus.CONFLICTING, ClaimStatus.UNCERTAIN}:
                claim.status = result.status
        else:
            claim.status = apply_primary_requirement(
                claim, result.status, plan, primary_supports=primary_supports
            )
        return attached, cited, primary_supports

    def _attach_evidence(
        self,
        event: Event,
        claim: Claim,
        by_ref: dict[int, _PacketSource],
        source_ref: int,
        evidence_type: EvidenceType,
        row: VerificationResult | CheapEvidenceJudgement | Any,
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
        if any(existing.source_item_id == item.id for existing in claim.evidence):
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
