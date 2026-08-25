from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.clock import utc_now
from app.core.config import get_settings
from app.core.prompts import load_prompt
from app.core.text import content_fingerprint, excerpt_in_source
from app.core.urls import canonicalize_url, url_domain
from app.domain.enums import (
    ClaimStatus,
    EventSourceRelation,
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
from app.providers.registry import ModelRole, get_search_provider, get_structured_provider
from app.repositories import (
    PipelineRunRepository,
    SourceItemRepository,
    SourceRepository,
)
from app.schemas import SourceCreate, SourceItemCreate
from app.schemas.verification import VerificationResult
from app.services.claim_service import CLAIM_STAGE, clamp_supported_status
from app.services.event_service import EventService
from app.services.fetching import HttpFetcher, extract_text
from app.services.research_service import freshness_for_event
from app.services.source_item_service import SourceItemService
from app.services.source_service import SourceService
from app.services.verification_policy import canonicalize_claim_type, select_claims

VERIFICATION_STAGE = "verification"
SNIPPET_CHARS = 1500


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
            result = self._run(event)
            run.status = PipelineStatus.SUCCESS
            run.finished_at = utc_now()
            run.metadata_json = {**(run.metadata_json or {}), **result}
            event.status = original_status
            self.session.flush()
            return {"skipped": False, "event_id": str(event.id), **result}
        except ProviderNotConfiguredError as exc:
            return self._fail(run, event, original_status, str(exc))
        except Exception as exc:
            return self._fail(run, event, original_status, str(exc))

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
            "sol": [],
            "attached": 0,
            "fetched": 0,
            "cited": 0,
            "verified": 0,
        }
        if not selected:
            return payload

        search = self.search or get_search_provider()
        llm = self.llm or get_structured_provider(ModelRole.VERIFICATION)
        freshness = freshness_for_event(event)
        system_prompt = load_prompt("verification.md")

        for row in selected:
            claim = row.claim
            status_before = claim.status
            queries = self._queries_for(claim, event)
            payload["queries"][str(claim.id)] = queries
            packet, fetched = self._packet_for(claim, search, queries, freshness)
            payload["fetched"] += fetched
            result = llm.generate_structured(
                system_prompt=system_prompt,
                user_prompt=self._user_prompt(event, claim, packet),
                schema=VerificationResult,
            )
            attached, cited = self._apply_result(event, claim, packet, result)
            payload["attached"] += attached
            payload["cited"] += cited
            payload["verified"] += 1
            payload["sol"].append(
                {
                    "claim_id": str(claim.id),
                    "status_before": status_before.value,
                    "status_after": claim.status.value,
                    "unresolved": result.unresolved,
                    "reason": result.reason,
                }
            )
        return payload

    def _queries_for(self, claim: Claim, event: Event) -> list[str]:
        place = " ".join(part for part in (event.locality, event.province) if part)
        base = " ".join(part for part in (claim.canonical_text, place) if part)
        kind = canonicalize_claim_type(claim.claim_type)
        extra = {
            "declaracion": "discurso OR comunicado",
            "cifra": "oficial OR boletín",
            "documento": "oficial OR boletín",
        }.get(kind)
        queries = [base]
        if extra:
            queries.append(f"{base} {extra}")
        return queries[: self.settings.max_verification_queries_per_claim]

    def _packet_for(
        self,
        claim: Claim,
        search: SearchProvider,
        queries: list[str],
        freshness: str,
    ) -> tuple[list[_PacketSource], int]:
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
            snippet = (row.excerpt or item.excerpt or item.clean_text or item.title or "")[:SNIPPET_CHARS]
            packet.append(
                _PacketSource(ref=ref, url=item.url, title=item.title or "", snippet=snippet, item=item)
            )
            ref += 1

        hits: list[SearchHit] = []
        per_query = self.settings.max_verification_results_per_query
        for text in queries:
            hits.extend(search.search(SearchQuery(text=text, count=per_query, freshness=freshness)))

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
                snippet = (existing.excerpt or existing.clean_text or hit.snippet or existing.title or "")[
                    :SNIPPET_CHARS
                ]
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
                    snippet=snippet,
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
        text = self.extract(html, fetched.url or url)
        return html, text

    def _user_prompt(self, event: Event, claim: Claim, packet: list[_PacketSource]) -> str:
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
            "Fuentes (source_ref 1..N, snippet truncado; no hay HTML crudo ni el Event entero):",
        ]
        for src in packet:
            lines.append(f"{src.ref}. title={src.title} url={src.url}\nsnippet={src.snippet}")
        return "\n".join(lines)

    def _apply_result(
        self,
        event: Event,
        claim: Claim,
        packet: list[_PacketSource],
        result: VerificationResult,
    ) -> tuple[int, int]:
        by_ref = {src.ref: src for src in packet}
        attached = 0
        cited = 0
        for row in result.evidence:
            src = by_ref.get(row.source_ref)
            if src is None:
                continue
            item = self._materialize_cited(src)
            if item is None:
                continue
            excerpt = (row.excerpt or "").strip() or None
            if excerpt and not excerpt_in_source(
                excerpt, item.clean_text, item.excerpt, item.title, src.snippet
            ):
                continue
            if any(existing.source_item_id == item.id for existing in claim.evidence):
                cited += 1
                continue
            evidence = ClaimEvidence(
                claim_id=claim.id,
                source_item_id=item.id,
                evidence_type=row.evidence_type,
                excerpt=excerpt,
                source_url=item.url,
                confidence=row.confidence,
            )
            self.session.add(evidence)
            claim.evidence.append(evidence)
            _, created_link = self.event_service.attach_source(
                event,
                item.id,
                relation_type=EventSourceRelation.ADDITIONAL,
                is_primary=False,
            )
            if created_link:
                attached += 1
            cited += 1

        self.session.flush()
        if result.unresolved:
            if result.status in {ClaimStatus.CONFLICTING, ClaimStatus.UNCERTAIN}:
                claim.status = result.status
        else:
            claim.status = clamp_supported_status(claim, result.status)
        return attached, cited

    def _materialize_cited(self, src: _PacketSource) -> SourceItem | None:
        if src.item is not None:
            return src.item
        url = src.url
        canonical = canonicalize_url(url)
        existing = self.items.get_by_canonical_url(canonical) or self.items.get_by_canonical_url(url)
        if existing is not None:
            src.item = existing
            return existing
        html = src.fetched_html or ""
        text = src.fetched_text or src.snippet
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
