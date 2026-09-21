from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.article_body import claim_ids_in_body_blocks
from app.domain.enums import PipelineStatus
from app.models import Article, ArticleVersion, PipelineRun
from app.repositories import ArticleRepository, EventRepository, PipelineRunRepository
from app.services.claim_card_presentation import contains_llm_reason
from app.services.evidence_snapshot import (
    evidence_snapshot_binding_for_version,
    is_unaudited_candidate,
    snapshot_sources_by_ref,
)
from app.services.feed_ranking import compact_public_claims
from app.services.pipeline_lock import AUDITING_STAGE, WRITING_STAGE
from app.services.verification_outcome import CLAIM_STAGE, VERIFICATION_STAGE

EXPORT_SCHEMA = "article-version-trace-1"

WRITING_MEANING_PRODUCED = "produced_this_version"
WRITING_MEANING_CONTEXT = "context_only"
WRITING_MEANING_NOT_RECORDED = "not_recorded"

_REWRITE_REASONS = {"audit_rewrite"}
_EDITORIAL_REASONS = {"editorial_minor", "editorial_update", "editorial_correction"}
_CONTEXT_REASONS = _REWRITE_REASONS | _EDITORIAL_REASONS

_TRACE_FIELDS = (
    "article_id",
    "event_id",
    "article_version",
    "article_version_id",
    "writing_run_id",
    "verification_run_id",
    "claims_fingerprint",
    "contract_version",
)


class VersionTraceError(ValueError):
    def __init__(self, code: str, http_status: int = 404) -> None:
        super().__init__(code)
        self.code = code
        self.http_status = http_status


def build_article_version_trace(
    session: Session,
    *,
    article_id: UUID,
    version_number: int | None,
) -> dict[str, Any]:
    articles = ArticleRepository(session)
    article = articles.get(article_id)
    if article is None:
        raise VersionTraceError("article_not_found", 404)

    requested: Literal["published"] | int
    if version_number is None:
        if article.published_version is None:
            raise VersionTraceError("not_published", 409)
        requested = "published"
        resolved = int(article.published_version)
    else:
        requested = int(version_number)
        resolved = int(version_number)

    version = articles.get_version(article.id, resolved)
    if version is None:
        raise VersionTraceError("version_not_found", 404)

    return _trace_for_resolved_version(session, article=article, version=version, requested=requested)


def _trace_for_resolved_version(
    session: Session,
    *,
    article: Article,
    version: ArticleVersion,
    requested: Literal["published"] | int,
) -> dict[str, Any]:
    target = int(version.version_number)
    event = EventRepository(session).get_with_details(article.event_id)
    if event is None:
        raise VersionTraceError("event_not_found", 404)

    lineage = PipelineRunRepository(session).list_lineage_runs(article.event_id)
    binding = evidence_snapshot_binding_for_version(lineage, target)
    snapshot = binding[0] if binding is not None else None
    snapshot_run = binding[1] if binding is not None else None

    missing: list[str] = []
    unresolvable: list[str] = []
    inconsistencies: list[dict[str, str]] = []

    writing_run_id, writing_source = _resolve_writing_run_id(
        snapshot=snapshot,
        snapshot_run=snapshot_run,
        lineage=lineage,
        target=target,
        change_reason=version.change_reason,
        inconsistencies=inconsistencies,
    )
    verification_run_id = _optional_id(snapshot.get("verification_run_id") if snapshot else None)
    coverage_run_id = _optional_id(snapshot.get("coverage_run_id") if snapshot else None)
    based_on_claim_run_id = _optional_id(snapshot.get("based_on_claim_run_id") if snapshot else None)
    claims_fingerprint = _optional_str(snapshot.get("claims_fingerprint") if snapshot else None)
    contract_version = _optional_str(snapshot.get("contract_version") if snapshot else None)

    if writing_run_id is None:
        missing.append("writing_run_id")
    if verification_run_id is None:
        missing.append("verification_run_id")
    if claims_fingerprint is None:
        missing.append("claims_fingerprint")
    if contract_version is None:
        missing.append("contract_version")

    _check_run_ref(
        session,
        field="writing_run_id",
        run_id=writing_run_id,
        expected_stage=WRITING_STAGE,
        expected_event_id=article.event_id,
        unresolvable=unresolvable,
        inconsistencies=inconsistencies,
    )
    _check_run_ref(
        session,
        field="verification_run_id",
        run_id=verification_run_id,
        expected_stage=VERIFICATION_STAGE,
        expected_event_id=article.event_id,
        unresolvable=unresolvable,
        inconsistencies=inconsistencies,
    )
    _check_run_ref(
        session,
        field="coverage_run_id",
        run_id=coverage_run_id,
        expected_stage=CLAIM_STAGE,
        expected_event_id=article.event_id,
        unresolvable=unresolvable,
        inconsistencies=inconsistencies,
    )
    if based_on_claim_run_id is not None:
        _check_run_ref(
            session,
            field="based_on_claim_run_id",
            run_id=based_on_claim_run_id,
            expected_stage=CLAIM_STAGE,
            expected_event_id=article.event_id,
            unresolvable=unresolvable,
            inconsistencies=inconsistencies,
        )

    if snapshot is not None:
        bound_version = snapshot.get("version")
        if bound_version is not None and int(bound_version) != target:
            inconsistencies.append(
                {
                    "field": "version",
                    "detail": "snapshot_version_mismatch",
                }
            )
        if snapshot_run is not None and snapshot_run.event_id != article.event_id:
            inconsistencies.append(
                {
                    "field": "snapshot_run_id",
                    "detail": "snapshot_run_event_mismatch",
                }
            )

    allowed = claim_ids_in_body_blocks(version.body_blocks)
    claims = (
        compact_public_claims(
            session,
            event,
            allowed_ids=allowed,
            freeze_to_version=target,
        )
        if snapshot is not None
        else []
    )
    payload = {
        "export_schema": EXPORT_SCHEMA,
        "article_id": str(article.id),
        "event_id": str(article.event_id),
        "article_version": target,
        "article_version_id": str(version.id),
        "writing_run_id": writing_run_id,
        "writing_run_meaning": _writing_meaning(version.change_reason, writing_run_id),
        "writing_run_source": writing_source,
        "verification_run_id": verification_run_id,
        "coverage_run_id": coverage_run_id,
        "based_on_claim_run_id": based_on_claim_run_id,
        "claims_fingerprint": claims_fingerprint,
        "contract_version": contract_version,
        "change_reason": version.change_reason,
        "stale_verification": snapshot.get("stale_verification") if snapshot else None,
        "selection": {
            "requested": requested,
            "resolved_version": target,
            "is_published_version": article.published_version is not None
            and int(article.published_version) == target,
            "is_current_version": int(article.current_version) == target,
        },
        "article_pointers": {
            "current_version": article.current_version,
            "published_version": article.published_version,
        },
        "snapshot_source": _snapshot_source_out(snapshot_run),
        "missing_fields": missing,
        "unresolvable_fields": unresolvable,
        "inconsistencies": inconsistencies,
        "version_content": {
            "headline": version.headline,
            "summary": version.summary,
            "body": version.body,
        },
        "claims": claims,
        "snapshot_sources": _compact_snapshot_sources(snapshot),
    }
    if contains_llm_reason(payload):
        raise RuntimeError("trace_export_leaked_llm_reason")
    for key in _TRACE_FIELDS:
        payload.setdefault(key, None)
    return payload


def _writing_meaning(change_reason: str | None, writing_run_id: str | None) -> str:
    if writing_run_id is None:
        return WRITING_MEANING_NOT_RECORDED
    if (change_reason or "") in _CONTEXT_REASONS:
        return WRITING_MEANING_CONTEXT
    return WRITING_MEANING_PRODUCED


def _resolve_writing_run_id(
    *,
    snapshot: dict[str, Any] | None,
    snapshot_run: PipelineRun | None,
    lineage: list[PipelineRun],
    target: int,
    change_reason: str | None,
    inconsistencies: list[dict[str, str]],
) -> tuple[str | None, str | None]:
    recorded = _optional_id(snapshot.get("writing_run_id") if snapshot else None)
    bound_to_target = _writing_runs_bound_to(lineage, target)
    if len(bound_to_target) > 1:
        ids = {str(run.id) for run in bound_to_target}
        if recorded is None:
            inconsistencies.append(
                {
                    "field": "writing_run_id",
                    "detail": "multiple_writing_runs_bound_to_version",
                }
            )
        elif recorded not in ids:
            inconsistencies.append(
                {
                    "field": "writing_run_id",
                    "detail": "snapshot_writing_run_not_bound_to_version",
                }
            )

    if recorded is not None:
        if len(bound_to_target) == 1 and str(bound_to_target[0].id) != recorded:
            if (change_reason or "") not in _CONTEXT_REASONS:
                inconsistencies.append(
                    {
                        "field": "writing_run_id",
                        "detail": "snapshot_writing_run_differs_from_version_bind",
                    }
                )
        return recorded, "snapshot"

    if (change_reason or "") in _EDITORIAL_REASONS:
        return None, None

    if len(bound_to_target) == 1:
        return str(bound_to_target[0].id), "writing_version_bind"

    if snapshot_run is not None and snapshot_run.stage == AUDITING_STAGE:
        version_before = (snapshot_run.metadata_json or {}).get("version_before")
        if version_before is not None:
            bound_before = _writing_runs_bound_to(lineage, int(version_before))
            if len(bound_before) == 1:
                return str(bound_before[0].id), "audit_version_before"
            if len(bound_before) > 1:
                inconsistencies.append(
                    {
                        "field": "writing_run_id",
                        "detail": "multiple_writing_runs_bound_to_version_before",
                    }
                )
    return None, None


def _writing_runs_bound_to(lineage: list[PipelineRun], version: int) -> list[PipelineRun]:
    found: list[PipelineRun] = []
    for run in lineage:
        if run.stage != WRITING_STAGE or run.status != PipelineStatus.SUCCESS:
            continue
        meta = run.metadata_json or {}
        if is_unaudited_candidate(meta):
            continue
        bound = meta.get("version")
        snap = meta.get("evidence_snapshot")
        if bound is None and isinstance(snap, dict):
            bound = snap.get("version")
        if bound is None:
            continue
        if int(bound) == int(version):
            found.append(run)
    return found


def _check_run_ref(
    session: Session,
    *,
    field: str,
    run_id: str | None,
    expected_stage: str,
    expected_event_id: UUID,
    unresolvable: list[str],
    inconsistencies: list[dict[str, str]],
) -> None:
    if run_id is None:
        return
    try:
        uid = UUID(run_id)
    except (TypeError, ValueError):
        unresolvable.append(field)
        return
    run = session.get(PipelineRun, uid)
    if run is None:
        unresolvable.append(field)
        return
    if run.event_id != expected_event_id:
        inconsistencies.append({"field": field, "detail": "run_event_mismatch"})
    if run.stage != expected_stage:
        inconsistencies.append({"field": field, "detail": "run_stage_mismatch"})


def _snapshot_source_out(run: PipelineRun | None) -> dict[str, str] | None:
    if run is None:
        return None
    return {"stage": run.stage, "run_id": str(run.id)}


def _compact_snapshot_sources(snapshot: dict[str, Any] | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for ref, source in snapshot_sources_by_ref(snapshot).items():
        rows.append(
            {
                "source_ref": ref,
                "name": source.get("name"),
                "title": source.get("title"),
                "url": source.get("url"),
                "domain": source.get("domain"),
            }
        )
    rows.sort(key=lambda row: int(row["source_ref"]))
    return rows


def _optional_id(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
