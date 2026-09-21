from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import ArticleStatus, ClaimImportance, ClaimStatus, EvidenceType, PipelineStatus
from app.models import Article, ArticleVersion, ClaimEvidence, PipelineRun
from app.providers.fakes import FakeStructuredLLM
from app.services.claim_coverage import claims_fingerprint
from app.services.claim_service import CLAIM_STAGE
from app.services.verification_outcome import VERIFICATION_STAGE, pair_from_runs
from app.services.writing_service import WritingService
from tests.editorial_snapshot import _complete_decision_for_claim
from tests.test_writing import _claim, _draft, _event, _item, _source


def _now():
    return datetime.now(timezone.utc)


def _claim_run(session: Session, event, claims, *, started_offset_seconds: int = 0) -> PipelineRun:
    fingerprint = claims_fingerprint(claims)
    run = PipelineRun(
        event_id=event.id,
        stage=CLAIM_STAGE,
        status=PipelineStatus.SUCCESS,
        started_at=_now(),
        finished_at=_now(),
        metadata_json={"claims_fingerprint": fingerprint, "coverage": {"coverage_gap": False}},
    )
    session.add(run)
    session.flush()
    if started_offset_seconds:
        run.started_at = run.started_at.replace(microsecond=0)
    return run


def _verify_run(session: Session, event, claim_run: PipelineRun, claims) -> PipelineRun:
    fingerprint = claims_fingerprint(claims)
    decisions = {str(claim.id): _complete_decision_for_claim(claim) for claim in claims}
    run = PipelineRun(
        event_id=event.id,
        stage=VERIFICATION_STAGE,
        status=PipelineStatus.SUCCESS,
        started_at=_now(),
        finished_at=_now(),
        metadata_json={
            "claims_fingerprint": fingerprint,
            "based_on_claim_run_id": str(claim_run.id),
            "decision_by_claim_id": decisions,
            "evaluated_claims": [
                {"claim_id": str(claim.id), "canonical_text": claim.canonical_text} for claim in claims
            ],
            "selected": [{"claim_id": str(claim.id)} for claim in claims],
        },
    )
    session.add(run)
    session.flush()
    return run


def _seed_event(session: Session):
    source = _source(session)
    item = _item(
        session,
        source.id,
        url="https://ejemplo.test/pairing",
        title="Nota",
        body="Un colectivo chocó en Pellegrini.",
        content_hash="pair1",
    )
    event = _event(session, item)
    claim = _claim(
        session,
        event,
        text="Un colectivo chocó en Pellegrini",
        claim_type="hecho",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.SUPPORTED,
    )
    session.add(
        ClaimEvidence(
            claim_id=claim.id,
            source_item_id=item.id,
            evidence_type=EvidenceType.SUPPORTS,
            excerpt="Un colectivo chocó en Pellegrini",
            source_url=item.url,
        )
    )
    session.flush()
    return event, claim, item


def test_pair_from_runs_matches_same_fingerprint_on_later_claim_run(db_session: Session) -> None:
    event, claim, _item = _seed_event(db_session)
    first = _claim_run(db_session, event, [claim])
    verify = _verify_run(db_session, event, first, [claim])
    later = _claim_run(db_session, event, [claim])
    later.started_at = first.started_at + timedelta(seconds=5)
    db_session.flush()
    assert later.id != first.id
    assert (later.metadata_json or {}).get("claims_fingerprint") == (first.metadata_json or {}).get(
        "claims_fingerprint"
    )
    runs = list(
        db_session.scalars(
            select(PipelineRun).where(PipelineRun.event_id == event.id).order_by(PipelineRun.started_at.desc())
        )
    )
    claim_run, verify_run = pair_from_runs(runs)
    assert verify_run is not None
    assert str(verify_run.id) == str(verify.id)
    assert str(claim_run.id) == str(first.id)


def test_write_reuses_verification_for_same_fingerprint_new_claim_run(db_session: Session) -> None:
    event, claim, _item = _seed_event(db_session)
    first = _claim_run(db_session, event, [claim])
    verify = _verify_run(db_session, event, first, [claim])
    later = _claim_run(db_session, event, [claim])
    later.started_at = first.started_at + timedelta(seconds=5)
    db_session.flush()
    llm = FakeStructuredLLM({"ArticleDraft": _draft()})
    result = WritingService(db_session, llm=llm).write(event.id, trigger="existing_event")
    assert result["written"] is True
    assert result["verification_run_id"] == str(verify.id)
    assert result["stale_verification"] is False
    assert result["coverage_run_id"] == str(first.id)
    assert result["based_on_claim_run_id"] == str(first.id)
    decision = (result.get("decision_by_claim_id") or {}).get(str(claim.id)) or {}
    assert decision.get("public_rendering")
    assert llm.calls, "should still call Writing when the pair exists"


def test_write_does_not_reuse_prior_verification_for_new_fingerprint(db_session: Session) -> None:
    event, claim, item = _seed_event(db_session)
    first = _claim_run(db_session, event, [claim])
    _verify_run(db_session, event, first, [claim])
    extra = _claim(
        db_session,
        event,
        text="El choque dejó cuatro heridos",
        claim_type="cifra",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.SINGLE_SOURCE,
        predicate="heridos",
        object_text="4",
    )
    session_item = item
    db_session.add(
        ClaimEvidence(
            claim_id=extra.id,
            source_item_id=session_item.id,
            evidence_type=EvidenceType.SUPPORTS,
            excerpt="cuatro heridos",
            source_url=session_item.url,
        )
    )
    db_session.flush()
    _claim_run(db_session, event, [claim, extra])
    llm = FakeStructuredLLM({"ArticleDraft": _draft()})
    result = WritingService(db_session, llm=llm).write(event.id, trigger="existing_event")
    assert result["written"] is False
    assert result["reason"] == "verification_not_paired"
    assert result.get("verification_run_id") in (None, "")
    assert not llm.calls
    assert db_session.scalars(select(Article).where(Article.event_id == event.id)).first() is None


def test_unpaired_write_leaves_published_v1_intact(db_session: Session) -> None:
    event, claim, item = _seed_event(db_session)
    first = _claim_run(db_session, event, [claim])
    verify = _verify_run(db_session, event, first, [claim])
    first_write = WritingService(db_session, llm=FakeStructuredLLM({"ArticleDraft": _draft()})).write(
        event.id, trigger="new_event"
    )
    assert first_write["written"] is True
    assert first_write["verification_run_id"] == str(verify.id)
    article = db_session.scalars(select(Article).where(Article.event_id == event.id)).one()
    headline = article.headline
    article.status = ArticleStatus.PUBLISHED
    article.published_version = article.current_version
    article.published_at = _now()
    db_session.flush()

    extra = _claim(
        db_session,
        event,
        text="El choque dejó cuatro heridos",
        claim_type="cifra",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.SINGLE_SOURCE,
        predicate="heridos",
        object_text="4",
    )
    db_session.add(
        ClaimEvidence(
            claim_id=extra.id,
            source_item_id=item.id,
            evidence_type=EvidenceType.SUPPORTS,
            excerpt="cuatro heridos",
            source_url=item.url,
        )
    )
    db_session.flush()
    _claim_run(db_session, event, [claim, extra])
    llm = FakeStructuredLLM({"ArticleDraft": _draft(headline="Titular de V2 no debe persistirse")})
    second = WritingService(db_session, llm=llm).write(event.id, trigger="existing_event")
    assert second["written"] is False
    assert second["reason"] == "verification_not_paired"
    db_session.refresh(article)
    assert article.published_version == 1
    assert article.current_version == 1
    assert article.headline == headline
    assert not llm.calls


def test_matching_verify_after_unpaired_skip_writes_without_touching_v1(db_session: Session) -> None:
    """Pollos race: older verify finishing must not write the newer unpaired fingerprint.

    After the matching SUCCESS verification exists, Writing may produce V2; live V1 stays.
    """
    event, claim, item = _seed_event(db_session)
    first = _claim_run(db_session, event, [claim])
    verify = _verify_run(db_session, event, first, [claim])
    first_write = WritingService(db_session, llm=FakeStructuredLLM({"ArticleDraft": _draft()})).write(
        event.id, trigger="new_event"
    )
    assert first_write["written"] is True
    article = db_session.scalars(select(Article).where(Article.event_id == event.id)).one()
    article.status = ArticleStatus.PUBLISHED
    article.published_version = article.current_version
    article.published_at = _now()
    live_headline = article.headline
    db_session.flush()

    extra = _claim(
        db_session,
        event,
        text="El choque dejó cuatro heridos",
        claim_type="cifra",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.SINGLE_SOURCE,
        predicate="heridos",
        object_text="4",
    )
    db_session.add(
        ClaimEvidence(
            claim_id=extra.id,
            source_item_id=item.id,
            evidence_type=EvidenceType.SUPPORTS,
            excerpt="cuatro heridos",
            source_url=item.url,
        )
    )
    db_session.flush()
    later_claims = [claim, extra]
    later = _claim_run(db_session, event, later_claims)
    later.started_at = first.started_at + timedelta(seconds=5)
    db_session.flush()

    skipped = WritingService(db_session, llm=FakeStructuredLLM({"ArticleDraft": _draft()})).write(
        event.id, trigger="new_event"
    )
    assert skipped["written"] is False
    assert skipped["reason"] == "verification_not_paired"

    later_verify = _verify_run(db_session, event, later, later_claims)
    second = WritingService(
        db_session,
        llm=FakeStructuredLLM({"ArticleDraft": _draft(headline="V2 con par vigente")}),
    ).write(event.id, trigger="existing_event")
    assert second["written"] is True
    assert second["verification_run_id"] == str(later_verify.id)
    assert second["version"] == 2
    db_session.refresh(article)
    assert article.published_version == 1
    assert article.current_version == 2
    v1 = db_session.scalars(
        select(ArticleVersion).where(
            ArticleVersion.article_id == article.id, ArticleVersion.version_number == 1
        )
    ).one()
    assert v1.headline == live_headline
    assert article.headline == "V2 con par vigente"


def test_last_written_run_skips_unaudited_candidate() -> None:
    from types import SimpleNamespace

    from app.services.article_context import claims_snapshot_for_version, last_written_run

    producer = SimpleNamespace(
        stage="writing",
        status=PipelineStatus.SUCCESS,
        metadata_json={
            "written": True,
            "reason": "initial",
            "version": 2,
            "claims_snapshot": [{"id": "producer"}],
        },
    )
    retry = SimpleNamespace(
        stage="writing",
        status=PipelineStatus.SUCCESS,
        metadata_json={
            "written": True,
            "reason": "unaudited_candidate",
            "version": 2,
            "claims_snapshot": [{"id": "retry"}],
        },
    )
    assert last_written_run([retry, producer]) is producer
    assert claims_snapshot_for_version([retry, producer], 2) == [{"id": "producer"}]


def test_pair_from_runs_rejects_fingerprint_with_incompatible_claim_ids(db_session: Session) -> None:
    from sqlalchemy.orm.attributes import flag_modified

    event, claim, _item = _seed_event(db_session)
    first = _claim_run(db_session, event, [claim])
    meta = dict(first.metadata_json or {})
    meta["evaluated_claims"] = [{"claim_id": str(claim.id), "canonical_text": claim.canonical_text}]
    first.metadata_json = meta
    flag_modified(first, "metadata_json")
    other_id = "00000000-0000-0000-0000-000000000099"
    db_session.add(
        PipelineRun(
            event_id=event.id,
            stage=VERIFICATION_STAGE,
            status=PipelineStatus.SUCCESS,
            started_at=_now(),
            finished_at=_now(),
            metadata_json={
                "claims_fingerprint": meta.get("claims_fingerprint"),
                "based_on_claim_run_id": str(first.id),
                "decision_by_claim_id": {other_id: {"claim_id": other_id, "status": "SUPPORTED"}},
                "evaluated_claims": [{"claim_id": other_id, "canonical_text": "otro"}],
            },
        )
    )
    db_session.flush()
    runs = list(
        db_session.scalars(
            select(PipelineRun).where(PipelineRun.event_id == event.id).order_by(PipelineRun.started_at.desc())
        )
    )
    claim_run, verify_run = pair_from_runs(runs)
    assert str(claim_run.id) == str(first.id)
    assert verify_run is None
