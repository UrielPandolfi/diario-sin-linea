import json
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.article_body import annotated_article_draft, plain_article_draft
from app.core.config import get_settings
from app.domain.enums import (
    ArticleStatus,
    ClaimImportance,
    ClaimStatus,
    EventStatus,
    EvidenceType,
    IngestionMethod,
    PipelineStatus,
)
from app.main import app
from app.models import Article, ArticleVersion, Claim, ClaimEvidence, PipelineRun
from app.providers.anthropic_provider import AnthropicJsonProvider, parse_json_payload, parse_structured
from app.providers.fakes import FakeStructuredLLM
from app.schemas import ArticleCreate, EventCreate, SourceCreate, SourceItemCreate
from app.schemas.writing import ArticleDraft, ArticleDraftBlock, ArticleDraftSegment
from app.services.article_context import select_context_claims
from app.services.article_service import ArticleService
from app.services.event_service import EventService
from app.services.material_change import detect_material_change
from app.services.source_item_service import SourceItemService
from app.services.source_service import SourceService
from app.services.verification_service import VERIFICATION_STAGE
from app.services.writing_service import WRITING_STAGE, WritingService


def _source(session: Session, **overrides):
    payload = {
        "name": "Fuente",
        "preferred_ingestion_method": IngestionMethod.RSS,
        "feed_url": "https://www.ejemplo.test/rss.xml",
        "is_monitored": True,
        "is_enabled": True,
        "domain": "ejemplo.test",
    }
    payload.update(overrides)
    return SourceService(session).create(SourceCreate(**payload))


def _item(
    session: Session,
    source_id,
    *,
    url: str,
    title: str,
    body: str,
    content_hash: str,
    raw_text: str | None = None,
):
    return SourceItemService(session).ingest(
        SourceItemCreate(
            source_id=source_id,
            url=url,
            canonical_url=url,
            content_hash=content_hash,
            title=title,
            clean_text=body,
            raw_text=raw_text,
            excerpt=body[:80],
        )
    ).item


def _event(session: Session, item, **overrides):
    payload = {
        "title_internal": "Choque en Pellegrini",
        "event_type": "accidente",
        "source_item_id": item.id,
        "started_at": datetime.now(timezone.utc),
        "locality": "Rosario",
        "province": "Santa Fe",
        "short_summary": "Un colectivo chocó en Rosario",
    }
    payload.update(overrides)
    return EventService(session).create(EventCreate(**payload))


def _claim(session: Session, event, *, text: str, claim_type: str, importance: ClaimImportance, status: ClaimStatus, **overrides):
    row = Claim(
        event_id=event.id,
        canonical_text=text,
        claim_type=claim_type,
        importance=importance,
        status=status,
        subject=overrides.get("subject"),
        predicate=overrides.get("predicate"),
        object_text=overrides.get("object_text"),
        normalized_value=overrides.get("normalized_value"),
        unit=overrides.get("unit"),
    )
    session.add(row)
    session.flush()
    return row


def _draft(**overrides) -> ArticleDraft:
    body = overrides.pop(
        "body",
        "Un colectivo chocó contra un automóvil en avenida Pellegrini.\n\nLas fuentes listadas coinciden en el lugar del hecho.",
    )
    headline = overrides.pop(
        "headline", "Un colectivo chocó contra un automóvil en avenida Pellegrini"
    )
    summary = overrides.pop(
        "summary", "El choque ocurrió esta tarde en Rosario y hay heridos, según fuentes locales."
    )
    draft = plain_article_draft(headline, summary, body)
    return draft.model_copy(update=overrides) if overrides else draft


def _service(session: Session, llm: FakeStructuredLLM) -> WritingService:
    return WritingService(session, llm=llm)


def _snapshot_row(claim_id, *, text: str, status: str, importance: str = "HIGH", value: str | None = None):
    return {
        "id": str(claim_id),
        "canonical_text": text,
        "status": status,
        "importance": importance,
        "normalized_value": value,
        "claim_type": "hecho",
    }


_DRAFT_JSON = (
    '{"headline": "H", "summary": "S", '
    '"body_blocks": [{"type": "paragraph", "segments": [{"text": "B", "claim_refs": []}]}]}'
)
_DRAFT_JSON_EMPTY_HEADLINE = (
    '{"headline": "", "summary": "S", '
    '"body_blocks": [{"type": "paragraph", "segments": [{"text": "B", "claim_refs": []}]}]}'
)


def test_parse_json_payload_strips_fences() -> None:
    assert parse_json_payload('```json\n{"headline": "H"}\n```') == {"headline": "H"}
    parsed = parse_structured("texto\n" + _DRAFT_JSON, ArticleDraft)
    assert parsed.headline == "H"


def test_anthropic_retries_invalid_json_then_validates() -> None:
    payloads = [
        "no es json",
        _DRAFT_JSON,
    ]
    client = SimpleNamespace(
        messages=SimpleNamespace(
            create=lambda **_k: SimpleNamespace(
                content=[SimpleNamespace(text=payloads.pop(0))]
            )
        )
    )
    provider = AnthropicJsonProvider(api_key="x", model="fake-model", client=client)
    result = provider.generate_structured(
        system_prompt="sys",
        user_prompt="user",
        schema=ArticleDraft,
    )
    assert result.headline == "H"
    assert payloads == []


def test_anthropic_retries_pydantic_validation_error() -> None:
    payloads = [
        _DRAFT_JSON_EMPTY_HEADLINE,
        _DRAFT_JSON,
    ]
    client = SimpleNamespace(
        messages=SimpleNamespace(
            create=lambda **_k: SimpleNamespace(
                content=[SimpleNamespace(text=payloads.pop(0))]
            )
        )
    )
    provider = AnthropicJsonProvider(api_key="x", model="fake-model", client=client)
    result = provider.generate_structured(
        system_prompt="sys",
        user_prompt="user",
        schema=ArticleDraft,
    )
    assert result.body_blocks[0].segments[0].text == "B"
    assert payloads == []
    try:
        ArticleDraft(headline="", summary="S", body_blocks=[])
    except ValidationError:
        pass
    else:
        raise AssertionError("empty headline should fail schema")


def test_detector_repetition_is_not_material() -> None:
    cid = uuid4()
    previous = [_snapshot_row(cid, text="Hubo un choque", status="SUPPORTED")]
    current = [_snapshot_row(cid, text="Hubo un choque", status="SUPPORTED")]
    change = detect_material_change(previous, current)
    assert change.is_material is False


def test_detector_new_high_and_confirmation_and_conflict_resolved() -> None:
    first = uuid4()
    second = uuid4()
    previous = [
        _snapshot_row(first, text="Hubo heridos", status="UNCERTAIN", importance="HIGH"),
        _snapshot_row(second, text="Fueron seis heridos", status="CONFLICTING", importance="HIGH", value="6"),
    ]
    current = [
        _snapshot_row(first, text="Hubo heridos", status="SUPPORTED", importance="HIGH"),
        _snapshot_row(second, text="Fueron seis heridos", status="SUPPORTED", importance="HIGH", value="6"),
        _snapshot_row(uuid4(), text="Cortaron el tránsito", status="SINGLE_SOURCE", importance="HIGH"),
    ]
    change = detect_material_change(previous, current)
    assert change.is_material is True
    assert "status_confirmed" in change.reasons
    assert "conflict_resolved" in change.reasons
    assert "new_high_claim" in change.reasons


def test_detector_only_low_new_is_not_material() -> None:
    cid = uuid4()
    previous = [_snapshot_row(cid, text="Hubo un choque", status="SUPPORTED", importance="HIGH")]
    current = [
        _snapshot_row(cid, text="Hubo un choque", status="SUPPORTED", importance="HIGH"),
        _snapshot_row(uuid4(), text="Otro medio repitió el choque", status="SINGLE_SOURCE", importance="LOW"),
    ]
    change = detect_material_change(previous, current)
    assert change.is_material is False


def test_context_omits_html_and_event_body(db_session: Session) -> None:
    source = _source(db_session)
    html = "<html><body><article>SECRETO raw_text no debe ir al prompt</article></body></html>"
    item = _item(
        db_session,
        source.id,
        url="https://ejemplo.test/nota",
        title="Nota",
        body="Un colectivo chocó en Pellegrini. TEXTO_LIMPIO_FUENTE.",
        content_hash="h1",
        raw_text=html,
    )
    event = _event(db_session, item)
    claim = _claim(
        db_session,
        event,
        text="Un colectivo chocó en Pellegrini",
        claim_type="hecho",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.SUPPORTED,
    )
    db_session.add(
        ClaimEvidence(
            claim_id=claim.id,
            source_item_id=item.id,
            evidence_type=EvidenceType.SUPPORTS,
            excerpt="Un colectivo chocó en Pellegrini",
            source_url=item.url,
        )
    )
    db_session.add(
        PipelineRun(
            event_id=event.id,
            stage=VERIFICATION_STAGE,
            status=PipelineStatus.SUCCESS,
            metadata_json={
                "selected": [{"claim_id": str(claim.id), "reasons": ["policy:hecho"]}],
                "sol": [
                    {
                        "claim_id": str(claim.id),
                        "status_before": "SINGLE_SOURCE",
                        "status_after": "SUPPORTED",
                        "unresolved": False,
                        "reason": "medios alineados",
                    }
                ],
            },
        )
    )
    db_session.flush()
    llm = FakeStructuredLLM({"ArticleDraft": _draft()})
    result = _service(db_session, llm).write(event.id, trigger="admin")
    assert result["written"] is True
    prompt = llm.user_prompts[0]
    assert "Un colectivo chocó en Pellegrini" in prompt
    assert "no conviertas otro hecho del mismo día en el titular" in prompt
    assert "confirmed_claims" in prompt
    assert "status_after" in prompt
    assert "source_contexts" in prompt
    assert "claim_refs" in prompt
    assert "C1" in prompt
    assert "TEXTO_LIMPIO_FUENTE" in prompt
    assert html not in prompt
    assert "raw_text" not in prompt
    assert "SECRETO" not in prompt
    assert "ANTHROPIC_API_KEY" not in prompt
    assert "DETECTED" not in prompt


def test_context_cap_does_not_cap_detector_snapshot(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(db_session, source.id, url="https://ejemplo.test/a", title="A", body="Choque", content_hash="h1")
    event = _event(db_session, item)
    _claim(
        db_session,
        event,
        text="Un colectivo chocó",
        claim_type="hecho",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.SUPPORTED,
    )
    _claim(
        db_session,
        event,
        text="Hubo cuatro heridos",
        claim_type="cifra",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.SUPPORTED,
        normalized_value="4",
    )
    db_session.flush()
    llm = FakeStructuredLLM({"ArticleDraft": [_draft(), _draft(headline="Hubo heridos en Pellegrini")]})
    service = _service(db_session, llm)
    original_cap = service.settings.max_writing_claims_per_event
    service.settings.max_writing_claims_per_event = 1
    try:
        first = service.write(event.id, trigger="admin")
        assert first["written"] is True
        assert len(first["claims_snapshot"]) == 2
        prompt = llm.user_prompts[0]
        payload = json.loads(prompt[prompt.find("{") :])
        bucket_texts = []
        for key in (
            "confirmed_claims",
            "single_source_claims",
            "conflicting_claims",
            "uncertain_claims",
            "disproven_claims",
            "outdated_claims",
        ):
            bucket_texts.extend(row["canonical_text"] for row in payload.get(key) or [])
        assert len(bucket_texts) == 1
        selected = select_context_claims(list(event.claims), limit=1)
        assert bucket_texts == [selected[0].canonical_text]
        _claim(
            db_session,
            event,
            text="Cortaron el tránsito",
            claim_type="estado",
            importance=ClaimImportance.HIGH,
            status=ClaimStatus.SINGLE_SOURCE,
        )
        db_session.flush()
        db_session.expire(event, ["claims"])
        second = service.write(event.id, trigger="admin")
        assert second["written"] is True
        assert second["version"] == 2
        assert "new_high_claim" in second["material_reasons"]
    finally:
        service.settings.max_writing_claims_per_event = original_cap


def test_first_write_creates_draft_and_keeps_event_status(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(db_session, source.id, url="https://ejemplo.test/a", title="A", body="Choque", content_hash="h1")
    event = _event(db_session, item)
    event.status = EventStatus.DETECTED
    _claim(
        db_session,
        event,
        text="Un colectivo chocó",
        claim_type="hecho",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.SUPPORTED,
    )
    db_session.flush()
    llm = FakeStructuredLLM({"ArticleDraft": _draft()})
    result = _service(db_session, llm).write(event.id, trigger="admin")
    db_session.refresh(event)
    article = db_session.get(Article, result["article_id"]) if result.get("article_id") else None
    assert result["skipped"] is False
    assert result["created"] is True
    assert result["written"] is True
    assert article is not None
    assert article.status == ArticleStatus.DRAFT
    assert article.current_version == 1
    assert article.body_blocks is not None
    assert "<" not in article.body
    assert "claim_refs" not in json.dumps(article.body_blocks)
    assert event.status == EventStatus.DETECTED
    versions = list(db_session.scalars(select(ArticleVersion).where(ArticleVersion.article_id == article.id)))
    assert len(versions) == 1


def test_second_write_same_claims_does_not_version(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(db_session, source.id, url="https://ejemplo.test/a", title="A", body="Choque", content_hash="h1")
    event = _event(db_session, item)
    _claim(
        db_session,
        event,
        text="Un colectivo chocó",
        claim_type="hecho",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.SUPPORTED,
    )
    db_session.flush()
    llm = FakeStructuredLLM({"ArticleDraft": _draft()})
    service = _service(db_session, llm)
    first = service.write(event.id, trigger="admin")
    second = service.write(event.id, trigger="admin")
    article = db_session.get(Article, first["article_id"])
    assert second["article_id"] == first["article_id"]
    assert second["created"] is False
    assert second["written"] is False
    assert second["reason"] == "no_material_change"
    assert llm.calls == ["ArticleDraft"]
    assert article is not None
    assert article.current_version == 1


def test_conflict_resolved_rewrites_draft(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(db_session, source.id, url="https://ejemplo.test/a", title="A", body="Choque", content_hash="h1")
    event = _event(db_session, item)
    claim = _claim(
        db_session,
        event,
        text="Hubo seis heridos",
        claim_type="cifra",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.CONFLICTING,
        normalized_value="6",
    )
    db_session.flush()
    llm = FakeStructuredLLM(
        {
            "ArticleDraft": [
                _draft(),
                _draft(headline="El choque dejó seis heridos en Pellegrini"),
            ]
        }
    )
    service = _service(db_session, llm)
    first = service.write(event.id, trigger="admin")
    claim.status = ClaimStatus.SUPPORTED
    db_session.flush()
    second = service.write(event.id, trigger="admin")
    article = db_session.get(Article, first["article_id"])
    assert second["written"] is True
    assert "conflict_resolved" in second["material_reasons"]
    assert article is not None
    assert article.current_version == 2
    assert article.status == ArticleStatus.DRAFT
    assert article.headline == "El choque dejó seis heridos en Pellegrini"


def test_published_article_is_not_rewritten(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(db_session, source.id, url="https://ejemplo.test/a", title="A", body="Choque", content_hash="h1")
    event = _event(db_session, item)
    _claim(
        db_session,
        event,
        text="Un colectivo chocó",
        claim_type="hecho",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.SUPPORTED,
    )
    article, _created = ArticleService(db_session).create_draft(
        ArticleCreate(
            event_id=event.id,
            headline="Titular publicado",
            summary="Resumen",
            body="Cuerpo",
            status=ArticleStatus.DRAFT,
        )
    )
    article.status = ArticleStatus.PUBLISHED
    db_session.flush()
    llm = FakeStructuredLLM({"ArticleDraft": _draft()})
    result = _service(db_session, llm).write(event.id, trigger="admin")
    db_session.refresh(article)
    count = db_session.scalar(select(func.count()).select_from(Article).where(Article.event_id == event.id))
    assert result["reason"] == "article_not_draft"
    assert result["written"] is False
    assert llm.calls == []
    assert count == 1
    assert article.current_version == 1
    assert article.status == ArticleStatus.PUBLISHED


def test_published_live_article_rewrites_on_material_change(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(db_session, source.id, url="https://ejemplo.test/a", title="A", body="Choque", content_hash="h1")
    event = _event(db_session, item)
    _claim(
        db_session,
        event,
        text="Un colectivo chocó",
        claim_type="hecho",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.SUPPORTED,
    )
    article, _created = ArticleService(db_session).create_draft(
        ArticleCreate(
            event_id=event.id,
            headline="Titular publicado",
            summary="Resumen",
            body="Cuerpo",
            status=ArticleStatus.DRAFT,
        )
    )
    article.status = ArticleStatus.PUBLISHED
    article.published_version = article.current_version
    article.published_at = datetime.now(timezone.utc)
    db_session.flush()
    extra = _claim(
        db_session,
        event,
        text="El choque dejó seis heridos",
        claim_type="hecho",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.SUPPORTED,
    )
    assert extra.id
    llm = FakeStructuredLLM({"ArticleDraft": _draft(headline="Titular actualizado")})
    result = _service(db_session, llm).write(event.id, trigger="admin")
    db_session.refresh(article)
    assert result["written"] is True
    assert article.status == ArticleStatus.DRAFT
    assert article.published_version == 1
    assert article.headline == "Titular actualizado"


def test_no_claims_skips_llm(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(db_session, source.id, url="https://ejemplo.test/a", title="A", body="Choque", content_hash="h1")
    event = _event(db_session, item)
    llm = FakeStructuredLLM({"ArticleDraft": _draft()})
    result = _service(db_session, llm).write(event.id, trigger="admin")
    count = db_session.scalar(select(func.count()).select_from(Article).where(Article.event_id == event.id))
    assert result["reason"] == "no_claims"
    assert result["written"] is False
    assert result["skipped"] is False
    assert llm.calls == []
    assert count == 0


def test_running_lock_skips_llm(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(db_session, source.id, url="https://ejemplo.test/a", title="A", body="Choque", content_hash="h1")
    event = _event(db_session, item)
    _claim(
        db_session,
        event,
        text="Un colectivo chocó",
        claim_type="hecho",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.SUPPORTED,
    )
    db_session.add(
        PipelineRun(event_id=event.id, stage=WRITING_STAGE, status=PipelineStatus.RUNNING, metadata_json={})
    )
    db_session.flush()
    llm = FakeStructuredLLM({"ArticleDraft": _draft()})
    result = _service(db_session, llm).write(event.id, trigger="admin")
    assert result["skipped"] is True
    assert result["reason"] == "already_running"
    assert llm.calls == []


def test_admin_write_accepted(db_session: Session, monkeypatch) -> None:
    queued: list[tuple] = []
    monkeypatch.setattr("app.api.admin.write_event_article.delay", lambda *args: queued.append(args))
    source = _source(db_session)
    item = _item(db_session, source.id, url="https://ejemplo.test/a", title="A", body="Choque", content_hash="h1")
    event = _event(db_session, item)
    db_session.commit()
    settings = get_settings()
    with TestClient(app) as client:
        login = client.post("/api/v1/admin/login", json={"password": settings.admin_password})
        assert login.status_code == 200
        response = client.post(f"/api/v1/admin/events/{event.id}/write")
        detail = client.get(f"/api/v1/admin/events/{event.id}")
    assert response.status_code == 202
    assert response.json()["queued"] is True
    assert queued == [(str(event.id), "admin")]
    assert detail.status_code == 200
    assert detail.json()["article"] is None


def test_admin_write_conflict_when_running(db_session: Session, monkeypatch) -> None:
    queued: list[tuple] = []
    monkeypatch.setattr("app.api.admin.write_event_article.delay", lambda *args: queued.append(args))
    source = _source(db_session)
    item = _item(db_session, source.id, url="https://ejemplo.test/a", title="A", body="Choque", content_hash="h1")
    event = _event(db_session, item)
    db_session.add(
        PipelineRun(event_id=event.id, stage=WRITING_STAGE, status=PipelineStatus.RUNNING, metadata_json={})
    )
    db_session.commit()
    settings = get_settings()
    with TestClient(app) as client:
        client.post("/api/v1/admin/login", json={"password": settings.admin_password})
        response = client.post(f"/api/v1/admin/events/{event.id}/write")
    assert response.status_code == 409
    assert queued == []


def test_verify_enqueues_write_only_on_success(monkeypatch) -> None:
    queued: list[tuple] = []

    class Sess:
        def commit(self) -> None:
            pass

        def rollback(self) -> None:
            pass

        def close(self) -> None:
            pass

    monkeypatch.setattr("app.workers.tasks.SessionLocal", Sess)
    monkeypatch.setattr("app.workers.tasks.write_event_article.delay", lambda *args: queued.append(args))
    from app.workers.tasks import verify_event_claims

    monkeypatch.setattr(
        "app.workers.tasks.VerificationService",
        lambda session: SimpleNamespace(verify=lambda *_a, **_k: {"skipped": False, "event_id": "eid"}),
    )
    verify_event_claims.run("00000000-0000-0000-0000-000000000001", "claims")
    assert queued == [("00000000-0000-0000-0000-000000000001", "claims")]

    queued.clear()
    monkeypatch.setattr(
        "app.workers.tasks.VerificationService",
        lambda session: SimpleNamespace(
            verify=lambda *_a, **_k: {"skipped": False, "event_id": "eid", "error": "boom"}
        ),
    )
    verify_event_claims.run("00000000-0000-0000-0000-000000000001", "claims")
    assert queued == []

    monkeypatch.setattr(
        "app.workers.tasks.VerificationService",
        lambda session: SimpleNamespace(
            verify=lambda *_a, **_k: {"skipped": True, "reason": "already_running"}
        ),
    )
    verify_event_claims.run("00000000-0000-0000-0000-000000000001", "admin")
    assert queued == []


def _seed_writeable_event(session: Session, *, extra_claims: list[str] | None = None):
    source = _source(session)
    item = _item(session, source.id, url="https://ejemplo.test/a", title="A", body="Choque", content_hash="h1")
    event = _event(session, item)
    claims = [
        _claim(
            session,
            event,
            text="Un colectivo chocó",
            claim_type="hecho",
            importance=ClaimImportance.HIGH,
            status=ClaimStatus.SUPPORTED,
        )
    ]
    for text in extra_claims or []:
        claims.append(
            _claim(
                session,
                event,
                text=text,
                claim_type="hecho",
                importance=ClaimImportance.HIGH,
                status=ClaimStatus.SUPPORTED,
            )
        )
    session.flush()
    return event, claims


def test_write_maps_c1_to_claim_uuid(db_session: Session) -> None:
    event, claims = _seed_writeable_event(db_session)
    draft = annotated_article_draft(
        "Un colectivo chocó en Pellegrini",
        "El choque ocurrió esta tarde en Rosario.",
        paragraphs=[
            [("Durante una conferencia este martes se informó el hecho.", [])],
            [("Un colectivo chocó.", ["C1"])],
        ],
    )
    result = _service(db_session, FakeStructuredLLM({"ArticleDraft": draft})).write(
        event.id, trigger="admin"
    )
    article = db_session.get(Article, result["article_id"])
    assert result["written"] is True
    assert article is not None
    assert article.body == (
        "Durante una conferencia este martes se informó el hecho.\n\nUn colectivo chocó."
    )
    assert "<" not in article.body
    segment = article.body_blocks[1]["segments"][0]
    assert segment["claim_ids"] == [str(claims[0].id)]
    assert "claim_refs" not in segment
    version = db_session.scalars(select(ArticleVersion).where(ArticleVersion.article_id == article.id)).one()
    assert version.body_blocks[1]["segments"][0]["claim_ids"] == [str(claims[0].id)]


def test_write_maps_multiple_claim_refs(db_session: Session) -> None:
    event, claims = _seed_writeable_event(db_session, extra_claims=["Hubo heridos"])
    draft = annotated_article_draft(
        "Choque con heridos",
        "El choque dejó heridos en Rosario.",
        paragraphs=[[("Un colectivo chocó y hubo heridos.", ["C1", "C2"])]],
    )
    result = _service(db_session, FakeStructuredLLM({"ArticleDraft": draft})).write(
        event.id, trigger="admin"
    )
    article = db_session.get(Article, result["article_id"])
    ordered = sorted(claims, key=lambda row: str(row.id))
    assert result["written"] is True
    assert article.body_blocks[0]["segments"][0]["claim_ids"] == [str(ordered[0].id), str(ordered[1].id)]


def test_write_rejects_unknown_claim_ref(db_session: Session) -> None:
    event, _claims = _seed_writeable_event(db_session)
    draft = annotated_article_draft(
        "Choque",
        "Resumen del choque en Rosario.",
        paragraphs=[[("Un colectivo chocó.", ["C99"])]],
    )
    result = _service(db_session, FakeStructuredLLM({"ArticleDraft": draft})).write(
        event.id, trigger="admin"
    )
    assert result["written"] is False
    assert "C99" in (result.get("error") or "")
    assert db_session.scalar(select(func.count()).select_from(Article).where(Article.event_id == event.id)) == 0


def test_write_rejects_raw_uuid_claim_ref(db_session: Session) -> None:
    event, claims = _seed_writeable_event(db_session)
    draft = annotated_article_draft(
        "Choque",
        "Resumen del choque en Rosario.",
        paragraphs=[[("Un colectivo chocó.", [str(claims[0].id)])]],
    )
    result = _service(db_session, FakeStructuredLLM({"ArticleDraft": draft})).write(
        event.id, trigger="admin"
    )
    assert result["written"] is False
    assert "UUID" in (result.get("error") or "")


def test_write_rejects_html_in_segments(db_session: Session) -> None:
    event, _claims = _seed_writeable_event(db_session)
    draft = ArticleDraft(
        headline="Choque",
        summary="Resumen del choque en Rosario.",
        body_blocks=[
            ArticleDraftBlock(
                segments=[ArticleDraftSegment(text="<b>Un colectivo chocó</b>", claim_refs=["C1"])]
            )
        ],
    )
    result = _service(db_session, FakeStructuredLLM({"ArticleDraft": draft})).write(
        event.id, trigger="admin"
    )
    assert result["written"] is False
    assert "HTML" in (result.get("error") or "")
