"""Audit aprobado y PublishService comparten la excepción de omisión en el titular."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import ClaimStatus, PipelineStatus
from app.models import PipelineRun
from app.providers.fakes import FakeStructuredLLM
from app.schemas import ArticleCreate
from app.schemas.auditing import ArticleAuditResult
from app.services.article_service import ArticleService
from app.services.audit_policy import HEADLINE_TOLERANCE_NOTE
from app.services.audit_service import AUDITING_STAGE, AuditService
from app.services.evidence_snapshot import bind_snapshot_to_version, persist_snapshot_fields
from app.services.publish_service import PublishService
from app.services.writing_service import WRITING_STAGE
from tests.test_audit import _event, _item, _pass_audit, _source
from tests.test_writing_certainty import _audit, _seed

_FLORENCIO = "88184369-da43-4acf-b600-40e4e9153860"
_CLAIM = "ef994d00-19aa-4c2a-b785-3bf6eb0857db"


def _export_path() -> Path:
    name = "sin_linea_revision_bloqueos.json"
    here = Path(__file__).resolve()
    candidates = [here.parents[2] / name, Path("/audit-export.json")]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]


def _florencio_version() -> dict:
    payload = json.loads(_export_path().read_text(encoding="utf-8"))
    for event in payload["sucesos"]:
        article = event.get("articulo") or {}
        if article.get("article_id") != _FLORENCIO:
            continue
        for version in event.get("versiones") or []:
            if version.get("version_number") == 1:
                return version
    raise AssertionError("florencio_v1_missing_from_export")


def _rendering(snapshot: dict) -> dict:
    decision = snapshot["decision_by_claim_id"][_CLAIM]
    return {
        "status": decision["status"],
        "public_rendering": deepcopy(decision["public_rendering"]),
    }


def _attach_writing_snapshot(session: Session, event, article, snapshot: dict) -> None:
    bound = bind_snapshot_to_version(snapshot, article.current_version)
    writing = PipelineRun(
        event_id=event.id,
        stage=WRITING_STAGE,
        status=PipelineStatus.SUCCESS,
        finished_at=datetime.now(timezone.utc),
        metadata_json={
            **persist_snapshot_fields(bound),
            "written": True,
            "version": article.current_version,
        },
    )
    session.add(writing)
    session.flush()


def _audit_issues(session: Session, event_id) -> list[dict]:
    run = session.scalars(
        select(PipelineRun)
        .where(PipelineRun.event_id == event_id, PipelineRun.stage == AUDITING_STAGE)
        .order_by(PipelineRun.started_at.desc())
    ).first()
    assert run is not None
    return list((run.metadata_json or {}).get("issues") or [])


def test_florencio_v1_audit_then_publish_keeps_low_and_permissions(db_session: Session) -> None:
    version = _florencio_version()
    snapshot = version["audit"]["run"]["metadata_json"]["evidence_snapshot"]
    before = _rendering(snapshot)
    source = _source(db_session, domain="florencio-publish.test", name="Florencio", feed_url="https://florencio-publish.test/rss.xml")
    item = _item(
        db_session,
        source.id,
        url="https://florencio-publish.test/nota",
        title="Florencio Varela",
        body=version["cuerpo"],
        content_hash="florencio-publish-v1",
    )
    event = _event(db_session, item, title_internal="Florencio Varela")
    article, _created = ArticleService(db_session).create_draft(
        ArticleCreate(
            event_id=event.id,
            headline=version["titular"],
            summary=version["bajada"],
            body=version["cuerpo"],
            body_blocks=version["body_blocks"],
        )
    )
    _attach_writing_snapshot(db_session, event, article, snapshot)
    stored = [
        issue
        for issue in version["audit"]["run"]["metadata_json"]["issues"]
        if issue.get("severity") in {"HIGH", "MEDIUM"}
    ]
    llm = FakeStructuredLLM(
        {"ArticleAuditResult": ArticleAuditResult.model_validate({"passed": False, "issues": stored})}
    )
    audited = AuditService(db_session, llm=llm).audit(event.id, trigger="test")
    assert audited["passed"] is True
    assert audited["rewrite_count"] == 0
    lows = [issue for issue in audited["issues"] if issue["severity"] == "LOW"]
    assert lows
    assert all(HEADLINE_TOLERANCE_NOTE in (issue.get("explanation") or "") for issue in lows if issue.get("claim_ref") == "headline" or issue.get("text") == version["titular"])
    assert not any(issue["severity"] in {"HIGH", "MEDIUM"} for issue in audited["issues"])

    published = PublishService(db_session).publish(event.id, trigger="test")
    assert published["published"] is True
    assert published["reason"] == "published"
    db_session.refresh(article)
    assert article.published_version == article.current_version
    kept = _audit_issues(db_session, event.id)
    assert any(issue["severity"] == "LOW" and HEADLINE_TOLERANCE_NOTE in (issue.get("explanation") or "") for issue in kept)
    assert _rendering(snapshot) == before
    assert before["public_rendering"]["headline_unattributed_allowed"] is False
    assert before["public_rendering"]["categorical_allowed"] is False
    assert before["status"] == "SINGLE_SOURCE"


def test_equivalent_aggregate_headline_publishes_without_fixed_ids(db_session: Session) -> None:
    headline = "El operativo dejó 42 detenidos y 8 prófugos"
    summary = "Según un informe policial, el operativo dejó 42 detenidos y 8 prófugos."
    lead = "Un informe policial informó que el operativo dejó 42 detenidos y 8 prófugos."
    event, article, rows, _refs = _seed(
        db_session,
        claims=[{"text": headline + ".", "status": ClaimStatus.SINGLE_SOURCE}],
        headline=headline,
        summary=summary,
        paragraphs=[[(lead, ["C1"])]],
    )
    decision = None
    audited = _audit(db_session, event, result=_pass_audit())[0]
    assert audited["passed"] is True
    assert audited["rewrite_count"] == 0
    assert any(issue["severity"] == "LOW" and HEADLINE_TOLERANCE_NOTE in (issue.get("explanation") or "") for issue in audited["issues"])
    run = db_session.scalars(
        select(PipelineRun).where(PipelineRun.event_id == event.id, PipelineRun.stage == AUDITING_STAGE)
    ).one()
    decision = run.metadata_json["evidence_snapshot"]["decision_by_claim_id"][str(rows[0].id)]
    flags = deepcopy(decision["public_rendering"])
    published = PublishService(db_session).publish(event.id, trigger="test")
    assert published["published"] is True
    assert decision["status"] == "SINGLE_SOURCE"
    assert decision["public_rendering"] == flags
    assert flags["headline_unattributed_allowed"] is False
    assert flags["categorical_allowed"] is False
    assert str(rows[0].id) not in {headline, "42"}


def test_publish_still_requires_a_passed_audit(db_session: Session) -> None:
    headline = "El relevo dejó 19 detenidos y 4 prófugos"
    event, _article, _rows, _refs = _seed(
        db_session,
        claims=[{"text": headline + ".", "status": ClaimStatus.SINGLE_SOURCE}],
        headline=headline,
        summary="Según un informe, el relevo dejó 19 detenidos y 4 prófugos.",
        paragraphs=[[("Un informe informó que el relevo dejó 19 detenidos y 4 prófugos.", ["C1"])]],
    )
    published = PublishService(db_session).publish(event.id, trigger="test")
    assert published["published"] is False
    assert published["reason"] == "audit_not_passed"


def test_excluded_headline_and_integrity_errors_still_block_publish(db_session: Session) -> None:
    guilt = "Pérez asesinó a la víctima y hay 12 detenidos"
    event, article, _rows, _refs = _seed(
        db_session,
        claims=[{"text": guilt + ".", "status": ClaimStatus.SINGLE_SOURCE}],
        headline=guilt,
        summary="Según un informe, Pérez asesinó a la víctima y hay 12 detenidos.",
        paragraphs=[[("Según un informe, Pérez asesinó a la víctima y hay 12 detenidos.", ["C1"])]],
    )
    audited = _audit(db_session, event, result=_pass_audit())[0]
    assert audited["passed"] is False
    published = PublishService(db_session).publish(event.id, trigger="test")
    assert published["published"] is False
    assert published["reason"] == "audit_not_passed"
    assert article.published_version is None

    source = _source(
        db_session,
        domain="integridad-publish.test",
        name="Integridad",
        feed_url="https://integridad-publish.test/rss.xml",
    )
    item = _item(
        db_session,
        source.id,
        url="https://integridad-publish.test/nota",
        title="Integridad",
        body="Hay 15 casos.",
        content_hash="integridad-publish",
    )
    gap_event = _event(db_session, item, title_internal="Cobertura central")
    gap_article, _created = ArticleService(db_session).create_draft(
        ArticleCreate(
            event_id=gap_event.id,
            headline="Hay 15 casos confirmados",
            summary="Según un informe, hay 15 casos.",
            body="Un informe informó que hay 15 casos.",
        )
    )
    snapshot = {
        "version": gap_article.current_version,
        "claims_fingerprint": "fp-gap",
        "verification_run_id": "ver-gap",
        "coverage_run_id": "cov-gap",
        "based_on_claim_run_id": "cov-gap",
        "coverage": {"coverage_gap": True, "expected_central": [{"proposition": "casos", "match": "none"}]},
        "article_context": {"verification": {}},
        "decision_by_claim_id": {},
        "evaluated_claims": [],
    }
    db_session.add(
        PipelineRun(
            event_id=gap_event.id,
            stage=AUDITING_STAGE,
            status=PipelineStatus.SUCCESS,
            finished_at=datetime.now(timezone.utc),
            metadata_json={
                "audited": True,
                "passed": True,
                "version_after": gap_article.current_version,
                "evidence_snapshot": snapshot,
            },
        )
    )
    db_session.flush()
    blocked = PublishService(db_session).publish(gap_event.id, trigger="test")
    assert blocked["published"] is False
    assert blocked["reason"] == "audit_not_passed"
