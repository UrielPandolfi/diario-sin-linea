from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import PipelineStatus
from app.models import Claim, PipelineRun
from app.services.article_context import build_article_context
from app.services.claim_coverage import claims_fingerprint
from app.services.claim_service import CLAIM_STAGE
from app.services.evidence_snapshot import capture_evidence_snapshot, persist_snapshot_fields
from app.services.verification_outcome import VERIFICATION_STAGE
from app.services.writing_service import WRITING_STAGE


def persist_version_snapshot(
    session: Session,
    event,
    article,
    *,
    coverage_gap: bool = False,
    stale: bool = False,
    central_unverified: list[str] | None = None,
    expected_central: list[dict] | None = None,
    deferred: list[dict] | None = None,
    fingerprint: str | None = None,
) -> dict:
    session.refresh(event)
    claims = list(event.claims)
    fp = fingerprint or (claims_fingerprint(claims) if claims else "fp-empty")
    unverified = list(central_unverified or [])
    if expected_central is not None:
        expected = expected_central
    elif coverage_gap:
        expected = [
            {
                "proposition": event.title_internal or "hecho central",
                "role": "existence",
                "match": "none",
                "gap_reason": "not_extracted",
            }
        ]
    elif claims:
        expected = [
            {
                "proposition": claims[0].canonical_text,
                "role": "other",
                "match": "equivalent",
                "match_claim_id": str(claims[0].id),
            }
        ]
    else:
        expected = []
    coverage = {
        "coverage_gap": coverage_gap,
        "expected_central": expected,
        "verification_incomplete": bool(unverified),
    }
    now = datetime.now(timezone.utc)
    claim_run = PipelineRun(
        event_id=event.id,
        stage=CLAIM_STAGE,
        status=PipelineStatus.SUCCESS,
        finished_at=now,
        metadata_json={"claims_fingerprint": fp, "coverage": coverage},
    )
    session.add(claim_run)
    session.flush()
    verify_run = None
    if not stale:
        decisions = {}
        selected = []
        sol = []
        for claim in claims:
            cid = str(claim.id)
            decisions[cid] = {
                "claim_id": cid,
                "status": claim.status.value,
                "unresolved": False,
                "final_reason": "evaluated",
                "proposition_role": "other",
                "support_basis": {
                    "known_independent_count": 1,
                    "statement_evidence_class": "authentic_primary",
                    "demotion": "none",
                },
            }
            selected.append({"claim_id": cid})
            sol.append(
                {
                    "claim_id": cid,
                    "status_before": claim.status.value,
                    "status_after": claim.status.value,
                    "unresolved": False,
                    "reason": "evaluated",
                }
            )
        verify_run = PipelineRun(
            event_id=event.id,
            stage=VERIFICATION_STAGE,
            status=PipelineStatus.SUCCESS,
            finished_at=now,
            metadata_json={
                "claims_fingerprint": fp,
                "based_on_claim_run_id": str(claim_run.id),
                "coverage": coverage,
                "evaluated_claims": [
                    {
                        "claim_id": str(claim.id),
                        "canonical_text": claim.canonical_text,
                        "assertion_key": fp,
                        "status": claim.status.value,
                    }
                    for claim in claims
                ],
                "decision_by_claim_id": decisions,
                "verification_incomplete": bool(unverified),
                "verification_budget": {
                    "limit": 5,
                    "selected_ids": [str(claim.id) for claim in claims if str(claim.id) not in unverified],
                    "deferred": list(deferred or []),
                    "central_unverified": unverified,
                },
                "selected": selected,
                "sol": sol,
            },
        )
        session.add(verify_run)
        session.flush()
    session.expire(event, ["claims"])
    runs = list(
        session.scalars(
            select(PipelineRun)
            .where(PipelineRun.event_id == event.id)
            .order_by(PipelineRun.started_at.desc())
        )
    )
    context = build_article_context(event, pipeline_runs=runs)
    snap = capture_evidence_snapshot(context, claim_run, verify_run, version=article.current_version)
    snap["coverage"] = coverage
    snap["verification_incomplete"] = bool(unverified)
    snap["central_unverified"] = unverified
    snap["stale_verification"] = stale
    writing = PipelineRun(
        event_id=event.id,
        stage=WRITING_STAGE,
        status=PipelineStatus.SUCCESS,
        finished_at=now,
        metadata_json={**persist_snapshot_fields(snap), "written": True, "version": article.current_version},
    )
    session.add(writing)
    session.flush()
    return snap


def attach_verify_to_latest_claim_run(session: Session, event) -> PipelineRun:
    claim_run = session.scalars(
        select(PipelineRun)
        .where(
            PipelineRun.event_id == event.id,
            PipelineRun.stage == CLAIM_STAGE,
            PipelineRun.status == PipelineStatus.SUCCESS,
        )
        .order_by(PipelineRun.started_at.desc())
    ).first()
    if claim_run is None:
        raise AssertionError("missing_claim_run")
    fp = (claim_run.metadata_json or {}).get("claims_fingerprint")
    claims = list(session.scalars(select(Claim).where(Claim.event_id == event.id)))
    coverage = (claim_run.metadata_json or {}).get("coverage") or {"coverage_gap": False, "expected_central": []}
    run = PipelineRun(
        event_id=event.id,
        stage=VERIFICATION_STAGE,
        status=PipelineStatus.SUCCESS,
        finished_at=datetime.now(timezone.utc),
        metadata_json={
            "claims_fingerprint": fp,
            "based_on_claim_run_id": str(claim_run.id),
            "coverage": coverage,
            "verification_incomplete": False,
            "verification_budget": {
                "limit": 5,
                "selected_ids": [str(claim.id) for claim in claims],
                "deferred": [],
                "central_unverified": [],
            },
            "decision_by_claim_id": {
                str(claim.id): {
                    "claim_id": str(claim.id),
                    "status": claim.status.value,
                    "unresolved": False,
                    "final_reason": "evaluated",
                    "proposition_role": "other",
                    "support_basis": {"known_independent_count": 2, "demotion": "none"},
                }
                for claim in claims
            },
            "evaluated_claims": [
                {"claim_id": str(claim.id), "canonical_text": claim.canonical_text, "status": claim.status.value}
                for claim in claims
            ],
            "selected": [{"claim_id": str(claim.id)} for claim in claims],
            "sol": [],
        },
    )
    session.add(run)
    session.flush()
    return run
