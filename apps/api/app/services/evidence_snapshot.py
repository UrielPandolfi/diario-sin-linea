from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from app.domain.enums import PipelineStatus
from app.models import PipelineRun
from app.schemas.writing import ArticleContext
from app.services.pipeline_lock import AUDITING_STAGE, WRITING_STAGE
from app.services.verification_outcome import writing_evidence_snapshot

UNAUDITED_CANDIDATE_REASON = "unaudited_candidate"

_SNAPSHOT_KEYS = (
    "contract_version",
    "coverage_run_id",
    "verification_run_id",
    "based_on_claim_run_id",
    "claims_fingerprint",
    "evaluated_claims",
    "decision_by_claim_id",
    "coverage",
    "verification_budget",
    "verification_incomplete",
    "central_unverified",
    "stale_verification",
    "version",
    "writing_run_id",
    "article_context",
)


def is_unaudited_candidate(meta: dict[str, Any] | None) -> bool:
    return (meta or {}).get("reason") == UNAUDITED_CANDIDATE_REASON


def snapshot_lacks_usable_verification(snapshot: dict[str, Any] | None) -> bool:
    """True when this version's snapshot cannot be audited as a paired contract."""
    if not snapshot:
        return True
    if snapshot.get("stale_verification"):
        return True
    if not snapshot.get("verification_run_id"):
        return True
    return not (snapshot.get("decision_by_claim_id") or {})


def capture_evidence_snapshot(
    article_context: ArticleContext,
    claim_run: PipelineRun | None,
    verify_run: PipelineRun | None,
    *,
    version: int | None = None,
) -> dict[str, Any]:
    snap = writing_evidence_snapshot(claim_run, verify_run, version=version)
    snap["article_context"] = json.loads(article_context.model_dump_json())
    return snap


def bind_snapshot_to_version(snapshot: dict[str, Any], version: int) -> dict[str, Any]:
    bound = dict(snapshot)
    bound["version"] = int(version)
    return bound


def snapshot_from_run_metadata(meta: dict[str, Any] | None) -> dict[str, Any] | None:
    raw = meta or {}
    nested = raw.get("evidence_snapshot")
    if isinstance(nested, dict) and _looks_like_snapshot(nested):
        return dict(nested)
    if _looks_like_snapshot(raw):
        return {key: raw.get(key) for key in _SNAPSHOT_KEYS if key in raw}
    return None


def _looks_like_snapshot(payload: dict[str, Any]) -> bool:
    if payload.get("article_context"):
        return True
    return bool(payload.get("contract_version") and (payload.get("coverage") is not None or payload.get("claims_fingerprint")))


def evidence_snapshot_binding_for_version(
    runs: Sequence[PipelineRun],
    version: int,
) -> tuple[dict[str, Any], PipelineRun] | None:
    """First audit/writing snapshot explicitly bound to `version`. Newest-first if `runs` is."""
    target = int(version)
    for run in runs:
        meta = run.metadata_json or {}
        if run.stage == AUDITING_STAGE and run.status in {PipelineStatus.SUCCESS, PipelineStatus.FAILED}:
            snap = meta.get("evidence_snapshot")
            version_after = meta.get("version_after")
            if isinstance(snap, dict) and version_after is not None and int(version_after) == target:
                return dict(snap), run
        if run.stage == WRITING_STAGE and run.status == PipelineStatus.SUCCESS:
            if is_unaudited_candidate(meta):
                continue
            snap = snapshot_from_run_metadata(meta)
            if snap is None:
                continue
            bound = snap.get("version") if snap.get("version") is not None else meta.get("version")
            if bound is not None and int(bound) == target:
                return snap, run
    return None


def evidence_snapshot_for_version(
    runs: Sequence[PipelineRun],
    version: int,
) -> dict[str, Any] | None:
    found = evidence_snapshot_binding_for_version(runs, version)
    return None if found is None else found[0]


def export_snapshot_for_version(
    runs: Sequence[PipelineRun],
    version: int,
) -> dict[str, Any] | None:
    """Snapshot bound to this version only. Never another version or live Verification."""
    found = evidence_snapshot_binding_for_version(runs, version)
    if found is None:
        return None
    snap, _run = found
    bound = snap.get("version")
    if bound is not None and int(bound) != int(version):
        return None
    return snap


def export_snapshot_coherence(
    snapshot: dict[str, Any] | None,
    *,
    version_number: int,
    writing_run_id: str | None,
    verification_run_id: str | None,
) -> list[str]:
    """Flags when an exported snapshot is not the C11 binding of `version_number`."""
    flags: list[str] = []
    if snapshot is None:
        return flags
    bound = snapshot.get("version")
    if bound is not None and int(bound) != int(version_number):
        flags.append("snapshot_version_mismatch")
    snap_write = snapshot.get("writing_run_id")
    if writing_run_id and snap_write and str(snap_write) != str(writing_run_id):
        flags.append("writing_run_mismatch")
    snap_verify = snapshot.get("verification_run_id")
    if not verification_run_id and snap_verify:
        flags.append("invented_verification_run_id")
    elif (
        verification_run_id
        and snap_verify
        and str(snap_verify) != str(verification_run_id)
    ):
        flags.append("verification_run_mismatch")
    return flags


def compact_decision_for_export(decision: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(decision, dict):
        return None
    basis = decision.get("support_basis") if isinstance(decision.get("support_basis"), dict) else None
    rendering = decision.get("public_rendering") if isinstance(decision.get("public_rendering"), dict) else None
    return {
        "evaluation_state": decision.get("evaluation_state"),
        "status": decision.get("status"),
        "reason_code": decision.get("reason_code"),
        "proposition_role": decision.get("proposition_role"),
        "verified_scope": decision.get("verified_scope"),
        "unsupported_scope": decision.get("unsupported_scope"),
        "final_reason": decision.get("final_reason"),
        "unresolved": decision.get("unresolved"),
        "support_basis": {
            "kind": basis.get("kind"),
            "known_independent": basis.get("known_independent"),
            "known_independent_count": basis.get("known_independent_count"),
            "unknown_groups": basis.get("unknown_groups"),
            "authoritative_independent": basis.get("authoritative_independent"),
            "statement_evidence_class": basis.get("statement_evidence_class"),
            "primary_access": basis.get("primary_access"),
            "demotion": basis.get("demotion"),
            "information_origins": list(basis.get("information_origins") or []),
            "document_keys": list(basis.get("document_keys") or []),
        }
        if basis
        else None,
        "public_rendering": rendering,
        "has_llm_reason": bool(decision.get("llm_reason")),
        "llm_reason_omitted": True,
    }


def bound_export_for_version(session, *, article_id, version_number: int) -> dict[str, Any]:
    """C11-explicit export: snapshot of N or null. Does not fill from another version."""
    from app.repositories import ArticleRepository, PipelineRunRepository
    from app.services.version_traceability import build_article_version_trace

    article = ArticleRepository(session).get(article_id)
    if article is None:
        raise ValueError("article_not_found")
    trace = build_article_version_trace(session, article_id=article_id, version_number=int(version_number))
    lineage = PipelineRunRepository(session).list_lineage_runs(article.event_id)
    snapshot = export_snapshot_for_version(lineage, int(version_number))
    flags = export_snapshot_coherence(
        snapshot,
        version_number=int(version_number),
        writing_run_id=trace.get("writing_run_id"),
        verification_run_id=trace.get("verification_run_id"),
    )
    usable = None if flags else snapshot
    return {
        "selection_method": "c11_explicit_version",
        "article_version": int(version_number),
        "writing_run_id": trace.get("writing_run_id"),
        "writing_run_meaning": trace.get("writing_run_meaning"),
        "verification_run_id": trace.get("verification_run_id"),
        "claims_fingerprint": trace.get("claims_fingerprint"),
        "stale_verification": trace.get("stale_verification"),
        "snapshot": usable,
        "coherence": flags,
        "c11_missing_fields": list(trace.get("missing_fields") or []),
    }


def article_context_from_snapshot(snapshot: dict[str, Any] | None) -> ArticleContext | None:
    if not snapshot:
        return None
    raw = snapshot.get("article_context")
    if not isinstance(raw, dict):
        return None
    try:
        return ArticleContext.model_validate(raw)
    except Exception:
        return None


def persist_snapshot_fields(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Flatten for writing-run metadata (tests read top-level keys) plus nested copy."""
    payload = {key: snapshot.get(key) for key in _SNAPSHOT_KEYS}
    payload["evidence_snapshot"] = dict(snapshot)
    return payload


def snapshot_context_claims(snapshot: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    states: dict[str, dict[str, Any]] = {}
    if not snapshot:
        return states
    context = snapshot.get("article_context")
    if not isinstance(context, dict):
        return states
    for key in (
        "confirmed_claims",
        "single_source_claims",
        "conflicting_claims",
        "uncertain_claims",
        "disproven_claims",
        "outdated_claims",
    ):
        for row in context.get(key) or []:
            if isinstance(row, dict) and row.get("id"):
                states[str(row["id"])] = row
    return states


def snapshot_sources_by_ref(snapshot: dict[str, Any] | None) -> dict[int, dict[str, Any]]:
    sources: dict[int, dict[str, Any]] = {}
    if not snapshot:
        return sources
    context = snapshot.get("article_context")
    if not isinstance(context, dict):
        return sources
    for row in context.get("sources") or []:
        if not isinstance(row, dict) or row.get("ref") is None:
            continue
        try:
            sources[int(row["ref"])] = row
        except (TypeError, ValueError):
            continue
    return sources


def snapshot_evaluated_texts(snapshot: dict[str, Any] | None) -> dict[str, str]:
    texts: dict[str, str] = {}
    if not snapshot:
        return texts
    for row in snapshot.get("evaluated_claims") or []:
        if not isinstance(row, dict) or not row.get("claim_id"):
            continue
        text = row.get("canonical_text")
        if text:
            texts[str(row["claim_id"])] = str(text)
    return texts
