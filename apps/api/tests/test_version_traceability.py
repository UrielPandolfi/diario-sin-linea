from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import get_settings
from app.domain.enums import (
    ArticleStatus,
    ClaimImportance,
    ClaimStatus,
    EditorialRevisionKind,
    EvidenceType,
    IngestionMethod,
    PipelineStatus,
)
from app.main import app
from app.models import Article, ArticleVersion, Claim, ClaimEvidence, PipelineRun
from app.providers.fakes import FakeStructuredLLM
from app.schemas import ArticleContentUpdate, ArticleCreate, EventCreate, SourceCreate, SourceItemCreate
from app.schemas.writing import ArticleDraft, ArticleDraftBlock, ArticleDraftSegment
from app.services.article_service import ArticleService
from app.services.audit_service import AUDITING_STAGE, REWRITE_CHANGE_REASON
from app.services.editorial_service import EditorialService
from app.services.event_service import EventService
from app.services.evidence_snapshot import bind_snapshot_to_version
from app.services.source_item_service import SourceItemService
from app.services.source_service import SourceService
from app.services.version_traceability import EXPORT_SCHEMA, VersionTraceError, build_article_version_trace
from app.services.writing_service import WRITING_STAGE, WritingService
from tests.editorial_snapshot import attach_verify_to_latest_claim_run, persist_version_snapshot


def _source(session: Session, hash_key: str):
    return SourceService(session).create(
        SourceCreate(
            name=f"Fuente {hash_key}",
            preferred_ingestion_method=IngestionMethod.RSS,
            feed_url=f"https://{hash_key}.test/rss.xml",
            is_monitored=True,
            is_enabled=True,
            domain=f"{hash_key}.test",
        )
    )


def _item(session: Session, source_id, hash_key: str, title: str, body: str):
    return SourceItemService(session).ingest(
        SourceItemCreate(
            source_id=source_id,
            url=f"https://{hash_key}.test/n",
            canonical_url=f"https://{hash_key}.test/n",
            content_hash=hash_key,
            title=title,
            clean_text=body,
        )
    ).item


def _blocks(claim_id, text: str) -> list[dict]:
    return [
        {
            "type": "paragraph",
            "segments": [{"text": text, "claim_ids": [str(claim_id)]}],
        }
    ]


def _seed(
    session: Session,
    *,
    hash_key: str,
    headline: str = "Hecho publicado",
    stale: bool = False,
    fingerprint: str | None = None,
):
    source = _source(session, hash_key)
    body = f"{headline}."
    item = _item(session, source.id, hash_key, headline, body)
    event = EventService(session).create(
        EventCreate(
            title_internal=headline,
            event_type="judicial",
            source_item_id=item.id,
            started_at=datetime.now(timezone.utc),
            locality="CABA",
            province="CABA",
            short_summary=headline,
        )
    )
    claim = Claim(
        event_id=event.id,
        canonical_text=headline,
        claim_type="hecho",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.SINGLE_SOURCE,
        subject="Hecho",
        predicate="ocurrió",
        object_text="ayer",
    )
    session.add(claim)
    session.flush()
    session.add(
        ClaimEvidence(
            claim_id=claim.id,
            source_item_id=item.id,
            evidence_type=EvidenceType.SUPPORTS,
            excerpt=headline,
            source_url=item.url,
        )
    )
    article, _created = ArticleService(session).create_draft(
        ArticleCreate(
            event_id=event.id,
            headline=headline,
            summary=f"Resumen {headline}",
            body=body,
            body_blocks=_blocks(claim.id, body),
        )
    )
    session.flush()
    snap = persist_version_snapshot(
        session,
        event,
        article,
        stale=stale,
        fingerprint=fingerprint or f"fp-{hash_key}-v1",
    )
    return event, article, claim, snap


def _mark_published(session: Session, article: Article, version_number: int) -> None:
    article.status = ArticleStatus.PUBLISHED
    article.published_version = version_number
    now = datetime.now(timezone.utc)
    article.published_at = now
    version = session.scalars(
        select(ArticleVersion).where(
            ArticleVersion.article_id == article.id,
            ArticleVersion.version_number == version_number,
        )
    ).first()
    if version is not None:
        version.published_at = now
    session.flush()


def _add_version(session: Session, event, article, *, headline: str, fingerprint: str):
    claim = event.claims[0]
    body = f"{headline}."
    article = ArticleService(session).update_content(
        article,
        ArticleContentUpdate(
            headline=headline,
            summary=f"Resumen {headline}",
            body=body,
            body_blocks=_blocks(claim.id, body),
            change_reason="material_change",
        ),
    )
    snap = persist_version_snapshot(session, event, article, fingerprint=fingerprint)
    return article, snap


def _writing_run(session: Session, event_id):
    return session.scalars(
        select(PipelineRun).where(
            PipelineRun.event_id == event_id,
            PipelineRun.stage == WRITING_STAGE,
            PipelineRun.status == PipelineStatus.SUCCESS,
        )
    ).all()


def _login(client: TestClient) -> None:
    response = client.post("/api/v1/admin/login", json={"password": get_settings().admin_password})
    assert response.status_code == 200


def _contains_key(payload, key: str) -> bool:
    if isinstance(payload, dict):
        if key in payload:
            return True
        return any(_contains_key(value, key) for value in payload.values())
    if isinstance(payload, list):
        return any(_contains_key(item, key) for item in payload)
    return False


def test_v1_published_v2_candidate_same_fingerprint_and_publish_switch(db_session: Session) -> None:
    event, article, _claim, snap_v1 = _seed(db_session, hash_key="c11a", headline="Versión uno")
    _mark_published(db_session, article, 1)
    v1_verify = snap_v1["verification_run_id"]
    v1_write = snap_v1["writing_run_id"]
    article, snap_v2 = _add_version(
        db_session, event, article, headline="Versión dos", fingerprint="fp-c11a-v1"
    )
    db_session.commit()

    published = build_article_version_trace(db_session, article_id=article.id, version_number=None)
    assert published["article_version"] == 1
    assert published["article_version_id"]
    assert published["writing_run_id"] == v1_write
    assert published["writing_run_meaning"] == "produced_this_version"
    assert published["verification_run_id"] == v1_verify
    assert published["claims_fingerprint"] == "fp-c11a-v1"
    assert published["contract_version"] == "editorial-evidence-1"
    assert published["export_schema"] == EXPORT_SCHEMA
    assert published["export_schema"] != published["contract_version"]
    assert published["selection"]["requested"] == "published"
    assert published["selection"]["is_published_version"] is True
    assert published["selection"]["is_current_version"] is False
    assert published["article_pointers"]["current_version"] == 2
    assert published["version_content"]["headline"] == "Versión uno"

    candidate = build_article_version_trace(db_session, article_id=article.id, version_number=2)
    assert candidate["article_version"] == 2
    assert candidate["writing_run_id"] == snap_v2["writing_run_id"]
    assert candidate["verification_run_id"] == snap_v2["verification_run_id"]
    assert candidate["verification_run_id"] != v1_verify
    assert candidate["writing_run_id"] != v1_write
    assert candidate["claims_fingerprint"] == "fp-c11a-v1"
    assert candidate["selection"]["is_published_version"] is False
    assert candidate["version_content"]["headline"] == "Versión dos"

    _mark_published(db_session, article, 2)
    db_session.commit()
    after = build_article_version_trace(db_session, article_id=article.id, version_number=None)
    assert after["article_version"] == 2
    assert after["writing_run_id"] == snap_v2["writing_run_id"]
    historic = build_article_version_trace(db_session, article_id=article.id, version_number=1)
    assert historic["article_version"] == 1
    assert historic["writing_run_id"] == v1_write
    assert historic["verification_run_id"] == v1_verify


def test_later_verification_does_not_change_v1_or_fill_legacy(db_session: Session) -> None:
    event, article, _claim, snap = _seed(db_session, hash_key="c11b", headline="V1 verificada")
    _mark_published(db_session, article, 1)
    v1_verify = snap["verification_run_id"]
    attach_verify_to_latest_claim_run(db_session, event)
    db_session.commit()
    again = build_article_version_trace(db_session, article_id=article.id, version_number=1)
    assert again["verification_run_id"] == v1_verify
    assert again["claims_fingerprint"] == snap["claims_fingerprint"]

    stale_event, stale_article, _stale_claim, stale_snap = _seed(
        db_session, hash_key="c11c", headline="Legacy sin verify", stale=True, fingerprint="fp-legacy"
    )
    writing = _writing_run(db_session, stale_event.id)[-1]
    meta = dict(writing.metadata_json or {})
    nested = dict(meta.get("evidence_snapshot") or {})
    nested.pop("writing_run_id", None)
    meta.pop("writing_run_id", None)
    meta["evidence_snapshot"] = nested
    writing.metadata_json = meta
    flag_modified(writing, "metadata_json")
    _mark_published(db_session, stale_article, 1)
    attach_verify_to_latest_claim_run(db_session, stale_event)
    db_session.commit()
    legacy = build_article_version_trace(db_session, article_id=stale_article.id, version_number=1)
    assert stale_snap["verification_run_id"] is None
    assert legacy["verification_run_id"] is None
    assert "verification_run_id" in legacy["missing_fields"]
    assert legacy["writing_run_id"] == str(writing.id)
    assert legacy["writing_run_source"] == "writing_version_bind"


def test_unpublished_and_foreign_version_are_explicit(db_session: Session) -> None:
    _event, article, _claim, _snap = _seed(db_session, hash_key="c11d", headline="Solo borrador")
    _other, other_article, _other_claim, _other_snap = _seed(
        db_session, hash_key="c11e", headline="Otro artículo"
    )
    _mark_published(db_session, other_article, 1)
    db_session.commit()

    try:
        build_article_version_trace(db_session, article_id=article.id, version_number=None)
        raise AssertionError("expected not_published")
    except VersionTraceError as exc:
        assert exc.code == "not_published"
        assert exc.http_status == 409

    draft = build_article_version_trace(db_session, article_id=article.id, version_number=1)
    assert draft["selection"]["is_published_version"] is False
    assert draft["article_pointers"]["published_version"] is None

    try:
        build_article_version_trace(db_session, article_id=article.id, version_number=9)
        raise AssertionError("expected version_not_found")
    except VersionTraceError as exc:
        assert exc.code == "version_not_found"

    db_session.commit()
    with TestClient(app) as client:
        _login(client)
        missing = client.get(f"/api/v1/admin/articles/{article.id}/trace")
        assert missing.status_code == 409
        assert missing.json()["detail"] == "not_published"
        explicit = client.get(f"/api/v1/admin/articles/{article.id}/versions/1/trace")
        assert explicit.status_code == 200
        foreign = client.get(f"/api/v1/admin/articles/{article.id}/versions/9/trace")
        assert foreign.status_code == 404
        unknown = client.get(f"/api/v1/admin/articles/{uuid4()}/trace")
        assert unknown.status_code == 404


def test_unresolvable_and_inconsistent_refs_stay_visible(db_session: Session) -> None:
    event, article, _claim, snap = _seed(db_session, hash_key="c11f", headline="Refs rotas")
    writing = _writing_run(db_session, event.id)[-1]
    gone = str(uuid4())
    claim_run_id = snap["coverage_run_id"]
    meta = dict(writing.metadata_json or {})
    nested = dict(meta.get("evidence_snapshot") or {})
    nested["verification_run_id"] = gone
    meta["verification_run_id"] = gone
    nested["coverage_run_id"] = snap["verification_run_id"]
    meta["coverage_run_id"] = snap["verification_run_id"]
    meta["evidence_snapshot"] = nested
    writing.metadata_json = meta
    flag_modified(writing, "metadata_json")
    _mark_published(db_session, article, 1)
    db_session.commit()

    payload = build_article_version_trace(db_session, article_id=article.id, version_number=1)
    assert payload["verification_run_id"] == gone
    assert "verification_run_id" in payload["unresolvable_fields"]
    assert payload["coverage_run_id"] == snap["verification_run_id"]
    assert any(
        row["field"] == "coverage_run_id" and row["detail"] == "run_stage_mismatch"
        for row in payload["inconsistencies"]
    )
    assert payload["writing_run_id"] == snap["writing_run_id"]
    assert claim_run_id != payload["coverage_run_id"]


def test_rewrite_and_editorial_revise_writing_meaning(db_session: Session) -> None:
    event, article, claim, snap = _seed(db_session, hash_key="c11g", headline="Antes del rewrite")
    _mark_published(db_session, article, 1)
    article = ArticleService(db_session).update_content(
        article,
        ArticleContentUpdate(
            headline="Después del rewrite",
            summary=article.summary,
            body="Después del rewrite.",
            body_blocks=_blocks(claim.id, "Después del rewrite."),
            change_reason=REWRITE_CHANGE_REASON,
        ),
    )
    db_session.add(
        PipelineRun(
            event_id=event.id,
            stage=AUDITING_STAGE,
            status=PipelineStatus.SUCCESS,
            finished_at=datetime.now(timezone.utc),
            metadata_json={
                "audited": True,
                "passed": True,
                "version_before": 1,
                "version_after": 2,
                "evidence_snapshot": bind_snapshot_to_version(dict(snap), 2),
            },
        )
    )
    db_session.flush()
    rewrite = build_article_version_trace(db_session, article_id=article.id, version_number=2)
    assert rewrite["writing_run_id"] == snap["writing_run_id"]
    assert rewrite["writing_run_meaning"] == "context_only"
    assert rewrite["writing_run_source"] == "snapshot"
    assert rewrite["verification_run_id"] == snap["verification_run_id"]

    EditorialService(db_session).revise(
        event.id,
        base_published_version=1,
        kind=EditorialRevisionKind.MINOR,
        headline="Corrección menor",
        summary=article.summary,
        body="Después del rewrite.\n\nAjuste de estilo editorial.",
    )
    db_session.commit()
    db_session.refresh(article)
    revised = build_article_version_trace(db_session, article_id=article.id, version_number=article.current_version)
    assert revised["writing_run_id"] is None
    assert revised["writing_run_meaning"] == "not_recorded"
    assert "writing_run_id" in revised["missing_fields"]
    assert revised["verification_run_id"] is None
    assert revised["change_reason"] == "editorial_minor"
    assert revised["version_content"]["headline"] == "Corrección menor"


def test_http_payload_auth_side_effects_and_public_isolation(db_session: Session) -> None:
    event, article, claim, snap = _seed(db_session, hash_key="c11h", headline="Export HTTP")
    _mark_published(db_session, article, 1)
    db_session.commit()
    runs_before = db_session.scalar(select(func.count()).select_from(PipelineRun))
    versions_before = db_session.scalar(select(func.count()).select_from(ArticleVersion))
    published_before = article.published_version

    with TestClient(app) as client:
        denied = client.get(f"/api/v1/admin/articles/{article.id}/trace")
        assert denied.status_code == 401
        _login(client)
        first = client.get(f"/api/v1/admin/articles/{article.id}/trace")
        repeat = client.get(f"/api/v1/admin/articles/{article.id}/trace")
        explicit = client.get(f"/api/v1/admin/articles/{article.id}/versions/1/trace")
        event_detail = client.get(f"/api/v1/admin/events/{event.id}")
        public = client.get(f"/api/v1/articles/{article.slug}")

    assert first.status_code == 200
    payload = first.json()
    assert payload["export_schema"] == EXPORT_SCHEMA
    assert payload["article_id"] == str(article.id)
    assert payload["event_id"] == str(event.id)
    assert payload["article_version"] == 1
    assert payload["writing_run_id"] == snap["writing_run_id"]
    assert payload["verification_run_id"] == snap["verification_run_id"]
    assert payload["claims_fingerprint"] == snap["claims_fingerprint"]
    assert payload["contract_version"] == "editorial-evidence-1"
    assert payload["version_content"]["headline"] == "Export HTTP"
    assert isinstance(payload["claims"], list)
    assert payload["claims"]
    assert payload["claims"][0]["id"] == str(claim.id)
    assert "llm_reason" not in payload
    assert "metadata_json" not in payload
    assert "demotion" not in (payload["claims"][0].get("presentation") or {})
    assert repeat.json() == first.json()
    explicit_body = explicit.json()
    assert explicit_body["selection"]["requested"] == 1
    for key in (
        "article_version",
        "article_version_id",
        "writing_run_id",
        "verification_run_id",
        "claims_fingerprint",
        "contract_version",
        "version_content",
        "claims",
    ):
        assert explicit_body[key] == payload[key]
    assert event_detail.status_code == 200
    versions = event_detail.json()["article"]["versions"]
    assert [row["version_number"] for row in versions] == [1]
    assert public.status_code == 200
    public_body = public.json()
    assert not _contains_key(public_body, "writing_run_id")
    assert not _contains_key(public_body, "export_schema")
    assert not _contains_key(public_body, "missing_fields")
    assert not _contains_key(public_body, "llm_reason")

    db_session.expire_all()
    assert db_session.scalar(select(func.count()).select_from(PipelineRun)) == runs_before
    assert db_session.scalar(select(func.count()).select_from(ArticleVersion)) == versions_before
    refreshed = db_session.get(Article, article.id)
    assert refreshed is not None
    assert refreshed.published_version == published_before


def test_writing_run_id_stamped_without_entering_llm_payload(db_session: Session) -> None:
    source = _source(db_session, "c11w")
    item = _item(db_session, source.id, "c11w", "Choque", "Un colectivo chocó en Pellegrini.")
    event = EventService(db_session).create(
        EventCreate(
            title_internal="Choque en Pellegrini",
            event_type="accidente",
            source_item_id=item.id,
            started_at=datetime.now(timezone.utc),
            locality="Rosario",
            province="Santa Fe",
            short_summary="Un colectivo chocó",
        )
    )
    db_session.add(
        Claim(
            event_id=event.id,
            canonical_text="Un colectivo chocó en Pellegrini",
            claim_type="hecho",
            importance=ClaimImportance.HIGH,
            status=ClaimStatus.SINGLE_SOURCE,
        )
    )
    db_session.flush()
    writer = FakeStructuredLLM(
        {
            "ArticleDraft": ArticleDraft(
                headline="Un colectivo chocó en Pellegrini",
                summary="El choque ocurrió en Rosario.",
                body_blocks=[
                    ArticleDraftBlock(
                        segments=[
                            ArticleDraftSegment(
                                text="Un colectivo chocó en Pellegrini.",
                                claim_refs=["C1"],
                            )
                        ]
                    )
                ],
            )
        }
    )
    result = WritingService(db_session, llm=writer).write(event.id, trigger="test")
    assert result.get("written") is True
    writing_run_id = result.get("writing_run_id")
    assert writing_run_id
    assert result["evidence_snapshot"]["writing_run_id"] == writing_run_id
    assert "writing_run_id" not in writer.user_prompts[0]
    run = db_session.get(PipelineRun, UUID(str(writing_run_id)))
    assert run is not None
    assert run.stage == WRITING_STAGE
    assert (run.metadata_json or {}).get("version") == result["version"]
