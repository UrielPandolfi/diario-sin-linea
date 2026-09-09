from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.clock import utc_now
from app.core.config import get_settings
from app.core.prompts import load_prompt
from app.core.source_content import has_extracted_body
from app.core.source_snippet import select_source_snippet
from app.core.text import excerpt_in_source, normalize_name
from app.core.urls import url_domain
from app.core.usage_context import usage_scope
from app.domain.enums import (
    ClaimImportance,
    ClaimStatus,
    EvidenceType,
    PipelineStatus,
    SourceItemStatus,
)
from app.models import Claim, ClaimEvidence, Event, EventSource, PipelineRun, Source, SourceItem
from app.providers.base import ProviderNotConfiguredError, StructuredLLMProvider
from app.providers.registry import ModelRole, get_claim_resolution_provider, get_structured_provider
from app.repositories import PipelineRunRepository
from app.schemas.claims import (
    ClaimExtractionBatch,
    ClaimResolutionBatch,
    ClaimResolutionItem,
    ExtractedClaim,
    ExtractedEvidence,
)
from app.schemas.editorial_evidence import CONTRACT_VERSION, CoverageMatch, DropReason, GapReason
from app.services.claim_coverage import (
    MergeOutcome,
    build_coverage_contract,
    claims_fingerprint,
    expected_centrals_from_event,
    match_expected_to_claims,
    record_drop,
    recover_expected_from_dropped,
    recover_from_source_body,
    split_compound_extracted,
)
from app.services.information_origin import assess_origins, has_support_evidence
from app.services.verification_outcome import (
    is_verification_locked,
    verification_view_for_event,
)

CLAIM_STAGE = "claim_resolution"

_EVIDENCE_RANK = {
    EvidenceType.CONTRADICTS: 4,
    EvidenceType.QUALIFIES: 3,
    EvidenceType.SUPPORTS: 2,
    EvidenceType.MENTIONS: 1,
}

_PROTECTED_STATUSES = {ClaimStatus.DISPROVEN, ClaimStatus.OUTDATED}


def _item_body(item: SourceItem) -> str:
    return (item.clean_text or "").strip()


def build_assertion_key(
    *,
    canonical_text: str,
    subject: str | None = None,
    predicate: str | None = None,
    normalized_value: str | None = None,
    object_text: str | None = None,
    unit: str | None = None,
) -> str:
    subj = (subject or "").strip()
    pred = (predicate or "").strip()
    if subj and pred:
        value = normalize_name(str(normalized_value if normalized_value not in (None, "") else object_text or ""))
        return f"{normalize_name(subj)}|{normalize_name(pred)}|{value}|{normalize_name(unit or '')}"
    return normalize_name(canonical_text or "")


def build_comparison_key(
    *,
    canonical_text: str,
    subject: str | None = None,
    predicate: str | None = None,
    unit: str | None = None,
    normalized_value: str | None = None,
    object_text: str | None = None,
) -> str:
    subj = (subject or "").strip()
    pred = (predicate or "").strip()
    if subj and pred:
        return f"{normalize_name(subj)}|{normalize_name(pred)}|{normalize_name(unit or '')}"
    return build_assertion_key(
        canonical_text=canonical_text,
        subject=subject,
        predicate=predicate,
        normalized_value=normalized_value,
        object_text=object_text,
        unit=unit,
    )


def assertion_key_for(claim: Claim | ExtractedClaim) -> str:
    return build_assertion_key(
        canonical_text=claim.canonical_text,
        subject=claim.subject,
        predicate=claim.predicate,
        normalized_value=claim.normalized_value,
        object_text=claim.object_text,
        unit=claim.unit,
    )


def comparison_key_for(claim: Claim | ExtractedClaim) -> str:
    return build_comparison_key(
        canonical_text=claim.canonical_text,
        subject=claim.subject,
        predicate=claim.predicate,
        normalized_value=claim.normalized_value,
        object_text=claim.object_text,
        unit=claim.unit,
    )


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _outlet_token(item: SourceItem, source: Source | None) -> str:
    domain = ""
    if source is not None and source.domain:
        domain = source.domain
    if not domain:
        domain = url_domain(item.canonical_url or item.url or "")
    return (domain or str(item.source_id)).lower()


def _claim_published_at(claim: Claim) -> datetime | None:
    supports: list[datetime] = []
    others: list[datetime] = []
    for row in claim.evidence:
        item = row.source_item
        if item is None or item.published_at is None:
            continue
        when = _aware(item.published_at)
        if when is None:
            continue
        if row.evidence_type == EvidenceType.SUPPORTS:
            supports.append(when)
        else:
            others.append(when)
    pool = supports or others
    return max(pool) if pool else None


def _competing_clock(members: list[Claim]) -> dict[Claim, datetime] | None:
    occurred = {claim: _aware(claim.occurred_at) for claim in members}
    published = {claim: _claim_published_at(claim) for claim in members}
    occurred_complete = all(value is not None for value in occurred.values())
    published_complete = all(value is not None for value in published.values())

    if occurred_complete:
        if len(set(occurred.values())) > 1:
            return occurred  # type: ignore[return-value]
        if published_complete and len(set(published.values())) > 1:
            return published  # type: ignore[return-value]
        if published_complete or all(value is None for value in published.values()):
            return occurred  # type: ignore[return-value]
        return None

    if published_complete:
        return published  # type: ignore[return-value]
    return None


def _independent_support_tokens(claim: Claim) -> set[str]:
    tokens: set[str] = set()
    for row in claim.evidence:
        if row.evidence_type != EvidenceType.SUPPORTS:
            continue
        item = row.source_item
        if item is None:
            continue
        source = item.source if item.source is not None else None
        tokens.add(_outlet_token(item, source))
    return tokens


@dataclass
class _PendingEvidence:
    evidence_type: EvidenceType
    excerpt: str | None
    confidence: float | None
    source_url: str | None


@dataclass
class _PendingClaim:
    canonical_text: str
    claim_type: str | None
    importance: ClaimImportance
    subject: str | None
    predicate: str | None
    object_text: str | None
    normalized_value: str | None
    unit: str | None
    occurred_at: datetime | None
    evidence: dict[UUID, _PendingEvidence] = field(default_factory=dict)


class ClaimService:
    def __init__(
        self,
        session: Session,
        *,
        extractor_llm: StructuredLLMProvider | None = None,
        resolver_llm: StructuredLLMProvider | None = None,
        escalated_resolver_llm: StructuredLLMProvider | None = None,
    ) -> None:
        self.session = session
        self.settings = get_settings()
        self.pipeline = PipelineRunRepository(session)
        self.extractor_llm = extractor_llm
        self.resolver_llm = resolver_llm
        self.escalated_resolver_llm = escalated_resolver_llm

    def resolve(self, event_id: UUID, *, trigger: str, context: dict | None = None) -> dict:
        event = self._load_event(event_id)
        if event is None:
            raise ValueError("event_not_found")
        original_status = event.status

        if self.pipeline.get_running(event_id, CLAIM_STAGE) is not None:
            return {
                "skipped": True,
                "reason": "already_running",
                "event_id": str(event_id),
                "persisted": 0,
            }

        run = PipelineRun(
            event_id=event.id,
            stage=CLAIM_STAGE,
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
                "persisted": 0,
            }

        try:
            with usage_scope(
                stage=CLAIM_STAGE,
                event_id=event.id,
                pipeline_run_id=run.id,
            ):
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
            "persisted": 0,
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
                selectinload(Event.claims).selectinload(Claim.evidence).selectinload(ClaimEvidence.source_item),
            )
            .where(Event.id == event_id)
        )
        return self.session.scalars(stmt).first()

    def _run(self, event: Event) -> dict:
        sources = self._numbered_sources(event)
        if not sources:
            return {
                "extracted": 0,
                "persisted": 0,
                "resolved": 0,
                "needs_external_verification": [],
                "escalated_claim_refs": [],
                "reason": "no_usable_sources",
                "contract_version": CONTRACT_VERSION,
            }
        extractor = self.extractor_llm or get_structured_provider(ModelRole.LIGHT_PROCESSING)
        batch = extractor.generate_structured(
            system_prompt=load_prompt("claim_extraction.md"),
            user_prompt=self._extraction_prompt(event, sources),
            schema=ClaimExtractionBatch,
        )
        split_claims: list[ExtractedClaim] = []
        for raw in batch.claims:
            split_claims.extend(split_compound_extracted(raw))
        outcome = self._merge_extracted(split_claims, sources)
        claims = self._persist(event, outcome.pending)
        self.session.flush()
        claims = self._reload_claims(event.id) if claims else []
        expected = match_expected_to_claims(expected_centrals_from_event(event), claims)
        recovered = recover_expected_from_dropped(
            expected,
            outcome.dropped_raw,
            sources,
            excerpt_ok=lambda rows, items: bool(self._valid_evidence(rows, items, require_body=True)),
        )
        still_open = [row for row in expected if row.match != CoverageMatch.EQUIVALENT]
        if still_open:
            recovered.extend(recover_from_source_body(still_open, sources))
        if recovered:
            recovered_outcome = self._merge_extracted(recovered, sources, require_body=True)
            if recovered_outcome.pending:
                self._persist(event, recovered_outcome.pending)
                self.session.flush()
                claims = self._reload_claims(event.id)
            outcome.dropped.extend(recovered_outcome.dropped)
            outcome.dropped_raw.extend(recovered_outcome.dropped_raw)
        coverage = build_coverage_contract(event=event, claims=claims, dropped=outcome.dropped)
        if coverage.coverage_gap:
            recovered_keys = {assertion_key_for(row) for row in recovered}
            for row in coverage.expected_central:
                if row.match == CoverageMatch.EQUIVALENT:
                    continue
                if row.gap_reason in {GapReason.DROPPED_INVALID_EXCERPT.value, GapReason.NOT_EXTRACTED.value}:
                    if recovered and not recovered_keys:
                        row.gap_reason = GapReason.RECOVERY_FAILED.value
                    elif recovered:
                        row.gap_reason = row.gap_reason or GapReason.RECOVERY_FAILED.value
        fingerprint = claims_fingerprint(claims)
        empty = {
            "extracted": len(batch.claims),
            "persisted": len(claims),
            "resolved": 0,
            "needs_external_verification": [],
            "escalated_claim_refs": [],
            "contract_version": CONTRACT_VERSION,
            "claims_fingerprint": fingerprint,
            "coverage": coverage.model_dump(mode="json"),
        }
        if not claims:
            return empty

        resolver = self.resolver_llm or get_claim_resolution_provider(escalated=False)
        resolution = resolver.generate_structured(
            system_prompt=load_prompt("claim_resolution.md"),
            user_prompt=self._resolution_prompt(event, claims),
            schema=ClaimResolutionBatch,
        )
        threshold = self.settings.claim_resolution_escalate_confidence
        escalate_refs = [
            item.claim_ref
            for item in resolution.items
            if _needs_resolution_escalation(item, threshold)
        ]
        escalated_done: list[int] = []
        if escalate_refs:
            escalated_llm = self.escalated_resolver_llm
            if escalated_llm is None and self.resolver_llm is None:
                escalated_llm = get_claim_resolution_provider(escalated=True)
            if escalated_llm is not None:
                override = escalated_llm.generate_structured(
                    system_prompt=load_prompt("claim_resolution.md"),
                    user_prompt=self._resolution_prompt(event, claims, refs=set(escalate_refs)),
                    schema=ClaimResolutionBatch,
                )
                resolution = _merge_resolution(resolution, override)
                escalated_done = escalate_refs
        needs = self._apply_resolution(claims, resolution, event_id=event.id)
        self.session.flush()
        claims = self._reload_claims(event.id)
        coverage = build_coverage_contract(event=event, claims=claims, dropped=outcome.dropped)
        fingerprint = claims_fingerprint(claims)
        return {
            "extracted": len(batch.claims),
            "persisted": len(claims),
            "resolved": len(claims),
            "needs_external_verification": needs,
            "escalated_claim_refs": escalated_done,
            "contract_version": CONTRACT_VERSION,
            "claims_fingerprint": fingerprint,
            "coverage": coverage.model_dump(mode="json"),
        }

    def _numbered_sources(self, event: Event) -> list[SourceItem]:
        links = [link for link in event.event_sources if link.source_item is not None]
        links.sort(key=lambda link: (not link.is_primary, link.added_at or utc_now(), str(link.source_item_id)))
        usable: list[SourceItem] = []
        for link in links:
            item = link.source_item
            if item.processing_status in (SourceItemStatus.FAILED, SourceItemStatus.SKIPPED):
                continue
            if not has_extracted_body(item):
                continue
            usable.append(item)
        return usable

    def _entity_names(self, event: Event) -> list[str]:
        names: list[str] = []
        for row in getattr(event, "event_entities", None) or []:
            entity = getattr(row, "entity", None)
            if entity is not None and entity.name:
                names.append(entity.name)
        return names

    def _snippet(self, item: SourceItem, event: Event) -> str:
        text = _item_body(item)
        return select_source_snippet(
            text,
            budget=self.settings.claim_extraction_source_chars,
            entity_names=self._entity_names(event),
            locality=event.locality,
            address=event.address_text,
        )

    def _extraction_prompt(self, event: Event, sources: list[SourceItem]) -> str:
        when = event.started_at or event.detected_at
        lines = [
            f"Título interno: {event.title_internal}",
            f"Tipo interno (puede estar mal; extraé hechos del texto, no del tipo): {event.event_type}",
            f"Lugar: {event.locality or ''} {event.province or ''}".strip(),
            f"Fecha: {when}",
            "Fuentes (source_ref 1..N, snippet truncado). Extraé los hechos concretos aunque no coincidan con el tipo interno.",
        ]
        for index, item in enumerate(sources, start=1):
            published = item.published_at.isoformat() if item.published_at else ""
            lines.append(
                f"{index}. title={item.title or ''} url={item.url} published_at={published}\n"
                f"snippet={self._snippet(item, event)}"
            )
        return "\n".join(lines)

    def _merge_extracted(
        self,
        extracted: list[ExtractedClaim],
        sources: list[SourceItem],
        *,
        require_body: bool = False,
    ) -> MergeOutcome:
        by_key: dict[str, _PendingClaim] = {}
        dropped: list = []
        dropped_raw: list[tuple[ExtractedClaim, str]] = []
        for raw in extracted:
            canonical = (raw.canonical_text or "").strip()
            if not canonical:
                dropped.append(record_drop(canonical_text="", reason=DropReason.EMPTY_CANONICAL.value))
                dropped_raw.append((raw, DropReason.EMPTY_CANONICAL.value))
                continue
            valid_evidence = self._valid_evidence(raw.evidence, sources, require_body=require_body)
            if not valid_evidence:
                dropped.append(
                    record_drop(canonical_text=canonical, reason=DropReason.INVALID_EXCERPT.value)
                )
                dropped_raw.append((raw, DropReason.INVALID_EXCERPT.value))
                continue
            key = assertion_key_for(raw)
            if not key:
                dropped.append(
                    record_drop(canonical_text=canonical, reason=DropReason.EMPTY_KEY.value)
                )
                dropped_raw.append((raw, DropReason.EMPTY_KEY.value))
                continue
            pending = by_key.get(key)
            if pending is None:
                pending = _PendingClaim(
                    canonical_text=canonical,
                    claim_type=raw.claim_type,
                    importance=raw.importance or ClaimImportance.MEDIUM,
                    subject=raw.subject,
                    predicate=raw.predicate,
                    object_text=raw.object_text,
                    normalized_value=raw.normalized_value,
                    unit=raw.unit,
                    occurred_at=_aware(raw.occurred_at),
                )
                by_key[key] = pending
            else:
                if normalize_name(pending.canonical_text) != normalize_name(canonical):
                    dropped.append(
                        record_drop(
                            canonical_text=canonical,
                            reason=DropReason.MERGED_INTO.value,
                            assertion_key=key,
                            merged_into=pending.canonical_text,
                        )
                    )
                    dropped_raw.append((raw, DropReason.MERGED_INTO.value))
                pending.canonical_text = canonical
                pending.claim_type = raw.claim_type or pending.claim_type
                pending.importance = raw.importance or pending.importance
                pending.subject = raw.subject if raw.subject else pending.subject
                pending.predicate = raw.predicate if raw.predicate else pending.predicate
                pending.object_text = raw.object_text if raw.object_text else pending.object_text
                pending.normalized_value = (
                    raw.normalized_value if raw.normalized_value else pending.normalized_value
                )
                pending.unit = raw.unit if raw.unit else pending.unit
                if raw.occurred_at is not None:
                    pending.occurred_at = _aware(raw.occurred_at)
            for item_id, row in valid_evidence.items():
                current = pending.evidence.get(item_id)
                if current is None or _EVIDENCE_RANK[row.evidence_type] > _EVIDENCE_RANK[current.evidence_type]:
                    pending.evidence[item_id] = row
                elif current.excerpt is None and row.excerpt:
                    current.excerpt = row.excerpt
                    if row.confidence is not None:
                        current.confidence = row.confidence
        return MergeOutcome(pending=by_key, dropped=dropped, dropped_raw=dropped_raw)

    def _valid_evidence(
        self,
        rows: list[ExtractedEvidence],
        sources: list[SourceItem],
        *,
        require_body: bool = False,
    ) -> dict[UUID, _PendingEvidence]:
        valid: dict[UUID, _PendingEvidence] = {}
        for row in rows:
            if row.source_ref < 1 or row.source_ref > len(sources):
                continue
            item = sources[row.source_ref - 1]
            excerpt = (row.excerpt or "").strip() or None
            blobs = (item.clean_text,) if require_body else (item.clean_text, item.excerpt, item.title)
            if excerpt and not excerpt_in_source(excerpt, *blobs):
                continue
            pending = _PendingEvidence(
                evidence_type=row.evidence_type,
                excerpt=excerpt,
                confidence=row.confidence,
                source_url=item.url,
            )
            current = valid.get(item.id)
            if current is None or _EVIDENCE_RANK[pending.evidence_type] > _EVIDENCE_RANK[current.evidence_type]:
                valid[item.id] = pending
        return valid

    def _persist(self, event: Event, pending_by_key: dict[str, _PendingClaim]) -> list[Claim]:
        existing_rows = list(
            self.session.scalars(
                select(Claim)
                .options(selectinload(Claim.evidence))
                .where(Claim.event_id == event.id)
            ).unique()
        )
        existing = {assertion_key_for(claim): claim for claim in existing_rows}
        persisted: list[Claim] = []
        for key, pending in pending_by_key.items():
            claim = existing.get(key)
            if claim is None:
                claim = Claim(
                    event_id=event.id,
                    canonical_text=pending.canonical_text,
                    claim_type=pending.claim_type,
                    importance=pending.importance,
                    status=ClaimStatus.SINGLE_SOURCE,
                    subject=pending.subject,
                    predicate=pending.predicate,
                    object_text=pending.object_text,
                    normalized_value=pending.normalized_value,
                    unit=pending.unit,
                    occurred_at=pending.occurred_at,
                )
                self.session.add(claim)
                self.session.flush()
                existing[key] = claim
            else:
                claim.canonical_text = pending.canonical_text
                claim.claim_type = pending.claim_type
                claim.importance = pending.importance
                claim.subject = pending.subject
                claim.predicate = pending.predicate
                claim.object_text = pending.object_text
                claim.normalized_value = pending.normalized_value
                claim.unit = pending.unit
                claim.occurred_at = pending.occurred_at
            by_item = {row.source_item_id: row for row in claim.evidence}
            for item_id, ev in pending.evidence.items():
                row = by_item.get(item_id)
                if row is None:
                    row = ClaimEvidence(
                        claim_id=claim.id,
                        source_item_id=item_id,
                        evidence_type=ev.evidence_type,
                        excerpt=ev.excerpt,
                        source_url=ev.source_url,
                        confidence=ev.confidence,
                    )
                    self.session.add(row)
                    claim.evidence.append(row)
                else:
                    if _EVIDENCE_RANK[ev.evidence_type] >= _EVIDENCE_RANK[row.evidence_type]:
                        row.evidence_type = ev.evidence_type
                    if ev.excerpt and not row.excerpt:
                        row.excerpt = ev.excerpt
                    if ev.confidence is not None:
                        row.confidence = ev.confidence
                    if ev.source_url:
                        row.source_url = ev.source_url
            persisted.append(claim)
        return persisted

    def _reload_claims(self, event_id: UUID) -> list[Claim]:
        stmt = (
            select(Claim)
            .options(
                selectinload(Claim.evidence).selectinload(ClaimEvidence.source_item).selectinload(SourceItem.source)
            )
            .where(Claim.event_id == event_id)
        )
        claims = list(self.session.scalars(stmt).unique())
        claims.sort(key=lambda claim: (assertion_key_for(claim), str(claim.id)))
        return claims

    def _resolution_prompt(
        self,
        event: Event,
        claims: list[Claim],
        refs: set[int] | None = None,
    ) -> str:
        groups: dict[str, list[tuple[int, Claim]]] = defaultdict(list)
        numbered = list(enumerate(claims, start=1))
        for index, claim in numbered:
            if refs is not None and index not in refs:
                continue
            groups[comparison_key_for(claim)].append((index, claim))
        lines = [
            f"Suceso: {event.title_internal}",
            f"Tipo: {event.event_type}",
            "Claims agrupados por comparison_key (claim_ref 1..N):",
        ]
        for comp_key, members in groups.items():
            lines.append(f"\ncomparison_key={comp_key}")
            for index, claim in members:
                occurred = claim.occurred_at.isoformat() if claim.occurred_at else ""
                lines.append(
                    f"{index}. assertion_key={assertion_key_for(claim)}\n"
                    f"canonical_text={claim.canonical_text}\n"
                    f"occurred_at={occurred}\n"
                    f"subject={claim.subject or ''} predicate={claim.predicate or ''} "
                    f"object_text={claim.object_text or ''} normalized_value={claim.normalized_value or ''} "
                    f"unit={claim.unit or ''}"
                )
                for row in claim.evidence:
                    item = row.source_item
                    domain = ""
                    published = ""
                    if item is not None:
                        domain = _outlet_token(item, item.source if item.source is not None else None)
                        if item.published_at is not None:
                            published = item.published_at.isoformat()
                    lines.append(
                        f"  - evidence_type={row.evidence_type.value} domain={domain} "
                        f"published_at={published} url={row.source_url or ''} excerpt={row.excerpt or ''}"
                    )
        return "\n".join(lines)

    def _apply_resolution(
        self,
        claims: list[Claim],
        batch: ClaimResolutionBatch,
        *,
        event_id: UUID,
    ) -> list[dict]:
        verify_run, view = verification_view_for_event(self.session, event_id)
        groups: dict[str, list[Claim]] = defaultdict(list)
        for claim in claims:
            groups[comparison_key_for(claim)].append(claim)
        by_ref = {item.claim_ref: item for item in batch.items}
        needs: list[dict] = []
        for index, claim in enumerate(claims, start=1):
            item = by_ref.get(index)
            members = groups[comparison_key_for(claim)]
            if is_verification_locked(claim, members, view, verify_run):
                if item is not None and item.needs_external_verification:
                    needs.append({"claim_id": str(claim.id), "claim_ref": index})
                continue
            status: ClaimStatus | None = item.status if item is not None else None
            if status is None:
                status = self._heuristic_status(claim)
            status = self._clamp_supported(claim, status)
            types = {row.evidence_type for row in claim.evidence}
            if EvidenceType.SUPPORTS in types and EvidenceType.CONTRADICTS in types:
                status = ClaimStatus.CONFLICTING
            claim.status = status
            if item is not None and item.needs_external_verification:
                needs.append({"claim_id": str(claim.id), "claim_ref": index})

        self._reconcile_competing_values(claims, verify_run=verify_run, view=view)
        return needs

    def _reconcile_competing_values(self, claims: list[Claim], *, verify_run, view) -> None:
        groups: dict[str, list[Claim]] = defaultdict(list)
        for claim in claims:
            groups[comparison_key_for(claim)].append(claim)
        for members in groups.values():
            keys = {assertion_key_for(claim) for claim in members}
            if len(keys) < 2:
                continue
            clock = _competing_clock(members)
            if clock is None:
                for claim in members:
                    if is_verification_locked(claim, members, view, verify_run):
                        continue
                    if claim.status not in _PROTECTED_STATUSES:
                        claim.status = ClaimStatus.UNCERTAIN
                continue
            latest = max(clock.values())
            latest_members = [claim for claim in members if clock[claim] == latest]
            for claim in members:
                if clock[claim] < latest and claim.status != ClaimStatus.DISPROVEN:
                    claim.status = ClaimStatus.OUTDATED
            latest_keys = {assertion_key_for(claim) for claim in latest_members}
            if len(latest_keys) >= 2:
                for claim in latest_members:
                    if claim.status == ClaimStatus.DISPROVEN:
                        continue
                    if is_verification_locked(claim, members, view, verify_run):
                        continue
                    claim.status = ClaimStatus.CONFLICTING
                continue
            for claim in latest_members:
                if is_verification_locked(claim, members, view, verify_run):
                    continue
                if claim.status == ClaimStatus.CONFLICTING:
                    claim.status = self._clamp_supported(claim, self._heuristic_status(claim))

    def _heuristic_status(self, claim: Claim) -> ClaimStatus:
        types = {row.evidence_type for row in claim.evidence}
        if EvidenceType.SUPPORTS in types and EvidenceType.CONTRADICTS in types:
            return ClaimStatus.CONFLICTING
        return clamp_supported_status(claim, ClaimStatus.SUPPORTED)

    def _clamp_supported(self, claim: Claim, status: ClaimStatus) -> ClaimStatus:
        return clamp_supported_status(claim, status)


def clamp_supported_status(claim: Claim, status: ClaimStatus) -> ClaimStatus:
    if status != ClaimStatus.SUPPORTED:
        return status
    from app.schemas.editorial_evidence import PropositionRole, StatementEvidenceClass

    assessment = assess_origins(claim)
    role = None
    try:
        from app.services.claim_coverage import proposition_role_for

        role = proposition_role_for(claim)
    except Exception:
        role = None
    if role == PropositionRole.UTTERANCE and assessment.statement_evidence_class == StatementEvidenceClass.AUTHENTIC_PRIMARY:
        return ClaimStatus.SUPPORTED
    if assessment.known_independent >= 2:
        return ClaimStatus.SUPPORTED
    if has_support_evidence(claim) or assessment.unknown_groups or assessment.known_independent == 1:
        return ClaimStatus.SINGLE_SOURCE
    return ClaimStatus.UNCERTAIN


def _needs_resolution_escalation(item: ClaimResolutionItem, threshold: float) -> bool:
    if item.confidence is not None and item.confidence < threshold:
        return True
    return (
        item.status == ClaimStatus.UNCERTAIN
        and item.needs_external_verification
        and bool(item.conflicts)
    )


def _merge_resolution(
    base: ClaimResolutionBatch,
    override: ClaimResolutionBatch,
) -> ClaimResolutionBatch:
    by_ref = {item.claim_ref: item for item in base.items}
    for item in override.items:
        by_ref[item.claim_ref] = item
    return ClaimResolutionBatch(items=list(by_ref.values()))
