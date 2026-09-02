from __future__ import annotations

from collections.abc import Sequence

from app.core.source_content import has_extracted_body
from app.core.urls import canonicalize_url, url_domain
from app.domain.enums import ClaimImportance, ClaimStatus, PipelineStatus
from app.models import Claim, Entity, Event, EventEntity, PipelineRun
from app.schemas.writing import (
    ArticleContext,
    ContextClaim,
    ContextEntity,
    ContextEventStub,
    ContextEvidence,
    ContextSource,
    ContextSourceText,
    ContextTimelineItem,
    ContextVerification,
    ContextVerificationSol,
)

_IMPORTANCE_RANK = {
    ClaimImportance.HIGH: 0,
    ClaimImportance.MEDIUM: 1,
    ClaimImportance.LOW: 2,
}

_STATUS_BUCKET = {
    ClaimStatus.SUPPORTED: "confirmed_claims",
    ClaimStatus.SINGLE_SOURCE: "single_source_claims",
    ClaimStatus.CONFLICTING: "conflicting_claims",
    ClaimStatus.UNCERTAIN: "uncertain_claims",
    ClaimStatus.DISPROVEN: "disproven_claims",
    ClaimStatus.OUTDATED: "outdated_claims",
}

VERIFICATION_STAGE = "verification"


def _truncate(value: str | None, limit: int) -> str | None:
    if not value:
        return None
    text = value.strip()
    if len(text) <= limit:
        return text
    return text[:limit]


def _claim_sort_key(claim: Claim) -> tuple:
    return (_IMPORTANCE_RANK.get(claim.importance, 9), str(claim.id))


def select_context_claims(claims: Sequence[Claim], *, limit: int) -> list[Claim]:
    ordered = sorted(claims, key=_claim_sort_key)
    if limit <= 0:
        return list(ordered)
    return ordered[:limit]


def compact_verification(run: PipelineRun | None) -> ContextVerification:
    if run is None or run.status != PipelineStatus.SUCCESS:
        return ContextVerification()
    raw = run.metadata_json or {}
    selected = raw.get("selected") if isinstance(raw.get("selected"), list) else []
    sol_rows: list[ContextVerificationSol] = []
    for row in raw.get("sol") or []:
        if not isinstance(row, dict) or not row.get("claim_id"):
            continue
        sol_rows.append(
            ContextVerificationSol(
                claim_id=str(row["claim_id"]),
                status_before=row.get("status_before"),
                status_after=row.get("status_after"),
                unresolved=row.get("unresolved"),
                reason=row.get("reason"),
            )
        )
    return ContextVerification(selected=list(selected), sol=sol_rows)


def last_success_run(runs: Sequence[PipelineRun], stage: str) -> PipelineRun | None:
    for run in runs:
        if run.stage == stage and run.status == PipelineStatus.SUCCESS:
            return run
    return None


def _to_context_claim(
    claim: Claim,
    *,
    ref: str,
    excerpt_chars: int,
    item_id_to_ref: dict,
    url_to_ref: dict[str, int],
) -> ContextClaim:
    evidence = []
    for row in claim.evidence:
        source_ref = None
        if row.source_item_id is not None:
            source_ref = item_id_to_ref.get(row.source_item_id)
        if source_ref is None:
            item = row.source_item
            url = (item.url if item is not None else None) or row.source_url
            if url:
                source_ref = url_to_ref.get(canonicalize_url(url) or url) or url_to_ref.get(url)
        if source_ref is None:
            continue
        evidence.append(
            ContextEvidence(
                source_ref=source_ref,
                evidence_type=row.evidence_type,
                excerpt=_truncate(row.excerpt, excerpt_chars),
            )
        )
    return ContextClaim(
        id=str(claim.id),
        ref=ref,
        canonical_text=claim.canonical_text,
        claim_type=claim.claim_type,
        importance=claim.importance,
        status=claim.status,
        subject=claim.subject,
        predicate=claim.predicate,
        object_text=claim.object_text,
        normalized_value=claim.normalized_value,
        unit=claim.unit,
        occurred_at=claim.occurred_at,
        evidence=evidence,
    )


def _sources(event: Event, *, limit: int) -> tuple[list[ContextSource], dict, dict[str, int]]:
    links = sorted(
        event.event_sources,
        key=lambda link: (not link.is_primary, str(link.id)),
    )
    rows: list[ContextSource] = []
    item_id_to_ref: dict = {}
    url_to_ref: dict[str, int] = {}
    for index, link in enumerate(links[:limit], start=1):
        item = link.source_item
        source = item.source if item is not None else None
        url = item.url if item is not None else ""
        domain = (source.domain if source is not None else None) or (url_domain(url) if url else None)
        name = (source.name if source is not None else None) or domain or url or f"Fuente {index}"
        rows.append(
            ContextSource(
                ref=index,
                name=name,
                domain=domain,
                url=url,
                title=item.title if item is not None else None,
                relation_type=link.relation_type,
                is_primary=link.is_primary,
                is_monitored=bool(source.is_monitored) if source is not None else False,
            )
        )
        if item is not None:
            item_id_to_ref[item.id] = index
            if item.url:
                url_to_ref[item.url] = index
                canonical = canonicalize_url(item.url)
                if canonical:
                    url_to_ref[canonical] = index
            if item.canonical_url:
                url_to_ref[item.canonical_url] = index
        elif url:
            url_to_ref[url] = index
    return rows, item_id_to_ref, url_to_ref


def _source_contexts(
    event: Event,
    *,
    limit: int,
    text_chars: int,
) -> list[ContextSourceText]:
    links = sorted(
        event.event_sources,
        key=lambda link: (not link.is_primary, str(link.id)),
    )
    rows: list[ContextSourceText] = []
    for link in links:
        if limit > 0 and len(rows) >= limit:
            break
        item = link.source_item
        if item is None or not has_extracted_body(item):
            continue
        source = item.source
        name = (source.name if source is not None else None) or url_domain(item.url) or item.url
        text = _truncate(item.clean_text, text_chars) or ""
        if not text:
            continue
        rows.append(
            ContextSourceText(
                source_id=str(item.id),
                source_name=name,
                url=item.url,
                title=item.title,
                published_at=item.published_at,
                text=text,
            )
        )
    return rows


def _entities(links: Sequence[EventEntity], entities: Sequence[Entity]) -> list[ContextEntity]:
    by_id = {entity.id: entity for entity in entities}
    rows: list[ContextEntity] = []
    for link in links:
        entity = by_id.get(link.entity_id)
        if entity is None:
            continue
        rows.append(
            ContextEntity(
                name=entity.name,
                entity_type=entity.entity_type,
                role=link.role,
            )
        )
    return rows


def _timeline(event: Event, claims: Sequence[Claim]) -> list[ContextTimelineItem]:
    rows: list[ContextTimelineItem] = []
    if event.started_at is not None:
        rows.append(
            ContextTimelineItem(
                occurred_at=event.started_at,
                text=event.title_internal,
                kind="event_start",
            )
        )
    for claim in claims:
        if claim.occurred_at is None:
            continue
        rows.append(
            ContextTimelineItem(
                occurred_at=claim.occurred_at,
                text=claim.canonical_text,
                kind="claim",
            )
        )
    for update in event.updates:
        rows.append(
            ContextTimelineItem(
                occurred_at=update.occurred_at,
                text=update.headline,
                kind="update",
            )
        )
    rows.sort(key=lambda row: (row.occurred_at is None, row.occurred_at, row.kind))
    return rows


def build_article_context(
    event: Event,
    *,
    entities: Sequence[Entity] = (),
    pipeline_runs: Sequence[PipelineRun] = (),
    max_claims: int = 40,
    max_sources: int = 20,
    excerpt_chars: int = 400,
    max_source_contexts: int = 6,
    source_context_chars: int = 5000,
) -> ArticleContext:
    selected = select_context_claims(list(event.claims), limit=max_claims)
    sources, item_id_to_ref, url_to_ref = _sources(event, limit=max_sources)
    claim_refs: dict[str, str] = {}
    buckets: dict[str, list[ContextClaim]] = {name: [] for name in _STATUS_BUCKET.values()}
    for index, claim in enumerate(selected, start=1):
        bucket = _STATUS_BUCKET.get(claim.status)
        if bucket is None:
            continue
        ref = f"C{index}"
        claim_refs[ref] = str(claim.id)
        buckets[bucket].append(
            _to_context_claim(
                claim,
                ref=ref,
                excerpt_chars=excerpt_chars,
                item_id_to_ref=item_id_to_ref,
                url_to_ref=url_to_ref,
            )
        )

    verification = compact_verification(last_success_run(pipeline_runs, VERIFICATION_STAGE))
    return ArticleContext(
        event=ContextEventStub(
            event_id=str(event.id),
            event_type=event.event_type,
            working_title=event.title_internal,
            locality=event.locality,
            province=event.province,
            neighborhood=event.neighborhood,
            started_at=event.started_at,
            short_summary=event.short_summary,
        ),
        confirmed_claims=buckets["confirmed_claims"],
        single_source_claims=buckets["single_source_claims"],
        conflicting_claims=buckets["conflicting_claims"],
        uncertain_claims=buckets["uncertain_claims"],
        disproven_claims=buckets["disproven_claims"],
        outdated_claims=buckets["outdated_claims"],
        entities=_entities(event.event_entities, entities),
        timeline=_timeline(event, selected),
        sources=sources,
        source_contexts=_source_contexts(
            event, limit=max_source_contexts, text_chars=source_context_chars
        ),
        claim_refs=claim_refs,
        verification=verification,
    )
