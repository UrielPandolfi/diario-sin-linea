from __future__ import annotations

from collections.abc import Sequence

from app.core.source_content import has_extracted_body
from app.core.urls import canonicalize_url, url_domain
from app.domain.enums import ClaimImportance, ClaimStatus, PipelineStatus
from app.models import Claim, Entity, Event, EventEntity, PipelineRun
from app.schemas.editorial_evidence import CoverageContract, EvaluationState, read_evaluation_state
from app.schemas.writing import (
    ArticleContext,
    ContextClaim,
    ContextClaimDecision,
    ContextEntity,
    ContextEventStub,
    ContextEvidence,
    ContextExpectedCentral,
    ContextSource,
    ContextSourceText,
    ContextSupportBasis,
    ContextTimelineItem,
    ContextVerification,
    ContextVerificationSol,
)
from app.services.claim_coverage import build_coverage_contract
from app.services.claim_service import comparison_key_for
from app.services.evidence_snapshot import is_unaudited_candidate
from app.services.verification_outcome import pair_from_runs

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


def claims_snapshot_for_version(runs: Sequence[PipelineRun], version: int) -> list[dict] | None:
    target = int(version)
    for run in runs:
        if run.stage != "writing" or run.status != PipelineStatus.SUCCESS:
            continue
        meta = run.metadata_json or {}
        if is_unaudited_candidate(meta):
            continue
        bound = meta.get("version")
        if bound is None or int(bound) != target:
            continue
        snapshot = meta.get("claims_snapshot")
        if isinstance(snapshot, list):
            return list(snapshot)
    return None


def compact_verification(
    run: PipelineRun | None,
    *,
    coverage_gap: bool = False,
    stale: bool = False,
    claim_run: PipelineRun | None = None,
    live_coverage: CoverageContract | None = None,
) -> ContextVerification:
    claim_meta = (claim_run.metadata_json if claim_run is not None else None) or {}
    verify_meta = (run.metadata_json if run is not None and run.status == PipelineStatus.SUCCESS else None) or {}
    coverage_raw = verify_meta.get("coverage") if isinstance(verify_meta.get("coverage"), dict) else None
    if coverage_raw is None:
        coverage_raw = claim_meta.get("coverage") if isinstance(claim_meta.get("coverage"), dict) else {}
    gap = coverage_gap or bool(coverage_raw.get("coverage_gap"))
    expected_rows: list[ContextExpectedCentral] = []
    for row in coverage_raw.get("expected_central") or []:
        if not isinstance(row, dict) or not row.get("proposition"):
            continue
        expected_rows.append(
            ContextExpectedCentral(
                proposition=str(row["proposition"]),
                role=row.get("role"),
                match=row.get("match"),
                gap_reason=row.get("gap_reason"),
                match_claim_id=str(row["match_claim_id"]) if row.get("match_claim_id") else None,
            )
        )
    if live_coverage is not None:
        gap = gap or bool(live_coverage.coverage_gap)
        live_rows: list[ContextExpectedCentral] = []
        for row in live_coverage.expected_central:
            proposition = (row.proposition or "").strip()
            if not proposition:
                continue
            match = row.match.value if hasattr(row.match, "value") else row.match
            role = row.role.value if hasattr(row.role, "value") else row.role
            live_rows.append(
                ContextExpectedCentral(
                    proposition=proposition,
                    role=role,
                    match=match,
                    gap_reason=row.gap_reason,
                    match_claim_id=str(row.match_claim_id) if row.match_claim_id else None,
                )
            )
        if live_rows:
            expected_rows = live_rows
    budget = verify_meta.get("verification_budget") if isinstance(verify_meta.get("verification_budget"), dict) else {}
    central_unverified = [str(item) for item in (budget.get("central_unverified") or [])]
    incomplete = bool(
        verify_meta.get("verification_incomplete")
        or coverage_raw.get("verification_incomplete")
        or central_unverified
    )
    decisions: dict[str, ContextClaimDecision] = {}
    for key, row in (verify_meta.get("decision_by_claim_id") or {}).items():
        if not isinstance(row, dict):
            continue
        state = read_evaluation_state(row)
        if state in {EvaluationState.SKIPPED, EvaluationState.PENDING, EvaluationState.FAILED}:
            continue
        basis_raw = row.get("support_basis") if isinstance(row.get("support_basis"), dict) else None
        basis = None
        if basis_raw is not None:
            basis = ContextSupportBasis.model_validate(basis_raw)
        decisions[str(key)] = ContextClaimDecision(
            claim_id=str(row.get("claim_id") or key),
            status=row.get("status"),
            unresolved=bool(row.get("unresolved")),
            final_reason=row.get("final_reason"),
            proposition_role=row.get("proposition_role"),
            support_basis=basis,
        )
    if run is None or run.status != PipelineStatus.SUCCESS:
        return ContextVerification(
            coverage_gap=gap,
            stale_verification=stale,
            claims_fingerprint=claim_meta.get("claims_fingerprint"),
            coverage_run_id=str(claim_run.id) if claim_run is not None else None,
            expected_central=expected_rows,
            verification_incomplete=incomplete,
            central_unverified=central_unverified,
        )
    selected = raw_selected(verify_meta)
    sol_rows: list[ContextVerificationSol] = []
    for row in verify_meta.get("sol") or []:
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
    return ContextVerification(
        selected=selected,
        sol=sol_rows,
        coverage_gap=gap,
        stale_verification=stale,
        claims_fingerprint=verify_meta.get("claims_fingerprint") or claim_meta.get("claims_fingerprint"),
        based_on_claim_run_id=str(verify_meta["based_on_claim_run_id"]) if verify_meta.get("based_on_claim_run_id") else None,
        coverage_run_id=str(claim_run.id) if claim_run is not None else None,
        verification_run_id=str(run.id),
        verification_incomplete=incomplete,
        central_unverified=central_unverified,
        expected_central=expected_rows,
        decision_by_claim_id=decisions,
    )


def raw_selected(meta: dict) -> list[dict]:
    selected = meta.get("selected") if isinstance(meta.get("selected"), list) else []
    return list(selected)


def last_success_run(runs: Sequence[PipelineRun], stage: str) -> PipelineRun | None:
    for run in runs:
        if run.stage == stage and run.status == PipelineStatus.SUCCESS:
            return run
    return None


def last_written_run(runs: Sequence[PipelineRun]) -> PipelineRun | None:
    """Last Writing SUCCESS that actually produced a version.

    `verification_not_paired` and `no_material_change` are SUCCESS with written=False.
    `unaudited_candidate` is SUCCESS with written=True but did not produce the text
    (retry to enqueue Audit). Using it as the previous snapshot would hide the producer.
    """
    for run in runs:
        if run.stage != "writing":
            continue
        if run.status != PipelineStatus.SUCCESS:
            continue
        meta = run.metadata_json or {}
        if meta.get("written") is not True:
            continue
        if is_unaudited_candidate(meta):
            continue
        return run
    return None


def _to_context_claim(
    claim: Claim,
    *,
    ref: str,
    excerpt_chars: int,
    item_id_to_ref: dict,
    url_to_ref: dict[str, int],
    decision: ContextClaimDecision | None = None,
    related_claim_ids: list[str] | None = None,
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
        proposition_role=decision.proposition_role if decision is not None else None,
        final_reason=decision.final_reason if decision is not None else None,
        support_basis=decision.support_basis if decision is not None else None,
        related_claim_ids=related_claim_ids or [],
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
    claim_ids: set[str] | None = None,
    include_source_contexts: bool = True,
) -> ArticleContext:
    claim_run, verify_run = pair_from_runs(list(pipeline_runs))
    coverage = ((claim_run.metadata_json if claim_run is not None else None) or {}).get("coverage") or {}
    coverage_gap = bool(isinstance(coverage, dict) and coverage.get("coverage_gap"))
    live_coverage = None
    try:
        live_coverage = build_coverage_contract(event=event, claims=list(event.claims), dropped=[])
        if live_coverage.coverage_gap:
            coverage_gap = True
    except Exception:
        live_coverage = None
    stale = verify_run is None and claim_run is not None and bool((claim_run.metadata_json or {}).get("claims_fingerprint"))
    verification = compact_verification(
        verify_run,
        coverage_gap=coverage_gap,
        stale=stale,
        claim_run=claim_run,
        live_coverage=live_coverage,
    )

    pool = list(event.claims)
    if claim_ids is not None:
        wanted = {str(claim_id) for claim_id in claim_ids}
        pool = [claim for claim in pool if str(claim.id) in wanted]
    selected = select_context_claims(pool, limit=max_claims)
    related: dict[str, list[str]] = {}
    for pair in ((claim_run.metadata_json if claim_run is not None else None) or {}).get("attribution_pairs", []):
        a, b = pair.get("attribution_claim_id"), pair.get("factual_claim_id")
        if a and b:
            related.setdefault(a, []).append(b)
            related.setdefault(b, []).append(a)
    groups: dict[str, list[str]] = {}
    for claim in event.claims:
        groups.setdefault(comparison_key_for(claim), []).append(str(claim.id))
    for members in groups.values():
        if len(members) < 2:
            continue
        for cid in members:
            others = [other for other in members if other != cid]
            bucket = related.setdefault(cid, [])
            for other in others:
                if other not in bucket:
                    bucket.append(other)
    sources, item_id_to_ref, url_to_ref = _sources(event, limit=max_sources)
    claim_refs: dict[str, str] = {}
    buckets: dict[str, list[ContextClaim]] = {name: [] for name in _STATUS_BUCKET.values()}
    verify_paired = verify_run is not None and verify_run.status == PipelineStatus.SUCCESS
    usable_as_fact = {"confirmed_claims", "single_source_claims"}
    for index, claim in enumerate(selected, start=1):
        bucket = _STATUS_BUCKET.get(claim.status)
        if bucket is None:
            continue
        decision = verification.decision_by_claim_id.get(str(claim.id))
        if verify_paired and bucket in usable_as_fact and decision is None:
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
                decision=decision,
                related_claim_ids=related.get(str(claim.id)),
            )
        )
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
        )
        if include_source_contexts
        else [],
        claim_refs=claim_refs,
        verification=verification,
    )
