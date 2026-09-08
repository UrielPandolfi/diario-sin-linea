from datetime import datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.article_body import annotated_article_draft, resolve_article_draft
from app.core.config import get_settings
from app.domain.enums import (
    ArticleStatus,
    CaseOutcome,
    CaseReason,
    ClaimImportance,
    ClaimStatus,
    EditorialRevisionKind,
    EvidenceType,
    IngestionMethod,
)
from app.main import app
from app.models import Claim, ClaimEvidence
from app.providers.fakes import FakeStructuredLLM
from app.schemas import ArticleContentUpdate, ArticleCreate, EventCreate, SourceCreate, SourceItemCreate
from app.schemas.auditing import ArticleAuditResult
from app.services.article_service import ArticleService
from app.services.audit_service import AuditService
from app.services.editorial_service import EditorialService
from app.services.event_service import EventService
from app.services.publish_service import PublishService
from app.services.source_item_service import SourceItemService
from app.services.source_service import SourceService
from tests.origin import ADMIN_ORIGIN


def _origin_post(client: TestClient, path: str, **kwargs):
    headers = {**ADMIN_ORIGIN, **kwargs.pop("headers", {})}
    return client.post(path, headers=headers, **kwargs)


def _seed_published(session: Session, *, with_claims: bool = True):
    source = SourceService(session).create(
        SourceCreate(
            name="Fuente",
            preferred_ingestion_method=IngestionMethod.RSS,
            feed_url="https://www.ejemplo.test/rss.xml",
            is_monitored=True,
            is_enabled=True,
            domain="ejemplo.test",
        )
    )
    item = SourceItemService(session).ingest(
        SourceItemCreate(
            source_id=source.id,
            url="https://ejemplo.test/n",
            canonical_url="https://ejemplo.test/n",
            content_hash="case-seed",
            title="Titular",
            clean_text="El documento oficial establece octubre.",
        )
    ).item
    event = EventService(session).create(
        EventCreate(
            title_internal="Medida",
            event_type="anuncio",
            source_item_id=item.id,
            started_at=datetime.now(timezone.utc),
            locality="Rosario",
            province="Santa Fe",
            short_summary="Medida",
            relevance_score=70,
        )
    )
    claim = Claim(
        event_id=event.id,
        canonical_text="La medida comienza en octubre",
        claim_type="hecho",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.SUPPORTED,
    )
    session.add(claim)
    session.flush()
    session.add(
        ClaimEvidence(
            claim_id=claim.id,
            source_item_id=item.id,
            evidence_type=EvidenceType.SUPPORTS,
            excerpt="octubre",
            source_url=item.url,
        )
    )
    if with_claims:
        body, blocks = resolve_article_draft(
            annotated_article_draft(
                "La medida empieza en septiembre",
                "Resumen",
                paragraphs=[
                    [("La medida comienza en octubre según el documento.", ["C1"])],
                    [("El anuncio se hizo en Rosario.", [])],
                ],
            ),
            claim_ref_map={"C1": str(claim.id)},
        )
    else:
        body, blocks = "Cuerpo de la noticia publicada.", None
    article, _created = ArticleService(session).create_draft(
        ArticleCreate(
            event_id=event.id,
            headline="La medida empieza en septiembre",
            summary="Resumen",
            body=body,
            body_blocks=blocks,
        )
    )
    AuditService(
        session, llm=FakeStructuredLLM({"ArticleAuditResult": ArticleAuditResult(passed=True, issues=[])})
    ).audit(event.id, trigger="test")
    PublishService(session).publish(event.id, trigger="test")
    session.commit()
    session.refresh(article)
    return event, article, claim


def _login(client: TestClient) -> None:
    settings = get_settings()
    login = client.post("/api/v1/admin/login", json={"password": settings.admin_password})
    assert login.status_code == 200


def test_admin_cases_unauthorized() -> None:
    with TestClient(app) as client:
        assert client.get("/api/v1/admin/cases").status_code == 401
        assert client.post("/api/v1/admin/cases/00000000-0000-0000-0000-000000000001/review").status_code == 401


def test_create_case_and_follow_up_privacy(db_session: Session, monkeypatch) -> None:
    monkeypatch.setattr("app.api.cases.allow_case_submit", lambda *_a, **_k: True)
    event, article, _claim = _seed_published(db_session)
    key = uuid4()
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/cases",
            headers={"Idempotency-Key": str(key)},
            json={
                "article_id": str(article.id),
                "reported_version_number": article.published_version,
                "reason": CaseReason.INCORRECT_FACT.value,
                "message": "La fecha de inicio está mal porque el documento dice octubre.",
                "email": "lector@example.test",
                "link_url": "https://fuente.test/doc",
            },
        )
        assert created.status_code == 201
        payload = created.json()
        assert payload["public_code"].startswith("SL-")
        token = payload["follow_up_url"].rsplit("/", 1)[-1]
        again = client.post(
            "/api/v1/cases",
            headers={"Idempotency-Key": str(key)},
            json={
                "article_id": str(article.id),
                "reported_version_number": article.published_version,
                "reason": CaseReason.INCORRECT_FACT.value,
                "message": "La fecha de inicio está mal porque el documento dice octubre.",
            },
        )
        assert again.status_code == 201
        assert again.json()["follow_up_url"] == payload["follow_up_url"]

        other = client.post(
            "/api/v1/cases",
            headers={"Idempotency-Key": str(uuid4())},
            json={
                "article_id": str(article.id),
                "reported_version_number": article.published_version,
                "reason": CaseReason.INCORRECT_FACT.value,
                "message": "La fecha de inicio está mal porque el documento dice octubre.",
            },
        )
        assert other.status_code == 201
        assert other.json()["follow_up_url"] != payload["follow_up_url"]

        follow = client.get(f"/api/v1/cases/follow-up/{token}")
        assert follow.status_code == 200
        assert follow.headers.get("cache-control", "").lower().find("no-store") >= 0
        body = follow.json()
        assert "email" not in body
        assert "ip_hash" not in body
        assert body["public_code"] == payload["public_code"]
        assert client.get(f"/api/v1/cases/follow-up/{article.id}").status_code == 404
        assert client.get(f"/api/v1/cases/follow-up/{payload['public_code']}").status_code == 404

        ArticleService(db_session).update_content(
            article,
            ArticleContentUpdate(
                headline=article.headline,
                summary=article.summary,
                body=article.body + "\n\nBorrador interno que nunca fue live.",
                change_reason="material_change",
            ),
        )
        db_session.commit()
        unpublished = client.post(
            "/api/v1/cases",
            headers={"Idempotency-Key": str(uuid4())},
            json={
                "article_id": str(article.id),
                "reported_version_number": article.current_version,
                "reason": CaseReason.OTHER.value,
                "message": "Versión que nunca fue live no debería aceptar el reporte.",
            },
        )
        assert unpublished.status_code == 422
        missing = client.post(
            "/api/v1/cases",
            headers={"Idempotency-Key": str(uuid4())},
            json={
                "article_id": str(article.id),
                "reported_version_number": 99,
                "reason": CaseReason.OTHER.value,
                "message": "Versión que nunca fue live no debería aceptar el reporte.",
            },
        )
        assert missing.status_code == 422
        general = client.post(
            "/api/v1/cases",
            headers={"Idempotency-Key": str(uuid4())},
            json={
                "reason": CaseReason.OTHER.value,
                "message": "Consulta general sobre el medio y cómo contactar redacción.",
            },
        )
        assert general.status_code == 201


def test_admin_origin_and_resolve_integrity(db_session: Session, monkeypatch) -> None:
    monkeypatch.setattr("app.api.cases.allow_case_submit", lambda *_a, **_k: True)
    event, article, _claim = _seed_published(db_session)
    with TestClient(app) as client:
        _login(client)
        denied = client.post(
            f"/api/v1/admin/events/{event.id}/archive",
            json={},
        )
        assert denied.status_code == 403
        created = client.post(
            "/api/v1/cases",
            headers={"Idempotency-Key": str(uuid4())},
            json={
                "article_id": str(article.id),
                "reported_version_number": article.published_version,
                "reason": CaseReason.INCORRECT_FACT.value,
                "message": "Hay un error factual en la fecha de vigencia de la medida.",
            },
        )
        listed = client.get("/api/v1/admin/cases")
        assert listed.status_code == 200
        case_id = next(row["id"] for row in listed.json() if row["public_code"] == created.json()["public_code"])
        review = _origin_post(client, f"/api/v1/admin/cases/{case_id}/review")
        assert review.status_code == 200
        note = _origin_post(client, f"/api/v1/admin/cases/{case_id}/notes", json={"note": "Chequeé el documento."})
        assert note.status_code == 200
        bad_resolve = _origin_post(
            client,
            f"/api/v1/admin/cases/{case_id}/resolve",
            json={"outcome": CaseOutcome.INQUIRY_ANSWERED.value, "public_resolution": "x"},
        )
        assert bad_resolve.status_code == 422
        need_corr = _origin_post(
            client,
            f"/api/v1/admin/cases/{case_id}/resolve",
            json={
                "outcome": CaseOutcome.CORRECTED.value,
                "public_resolution": "Corregimos la fecha según el documento oficial de octubre.",
            },
        )
        assert need_corr.status_code == 422
        with_other = _origin_post(
            client,
            f"/api/v1/admin/cases/{case_id}/resolve",
            json={
                "outcome": CaseOutcome.INQUIRY_ANSWERED.value,
                "public_resolution": "Respondimos la consulta general sin cambiar la noticia publicada.",
                "linked_correction_id": str(uuid4()),
            },
        )
        assert with_other.status_code == 422


def test_editorial_revise_claims_conflict_history_and_hold(db_session: Session, monkeypatch) -> None:
    monkeypatch.setattr("app.api.cases.allow_case_submit", lambda *_a, **_k: True)
    event, article, claim = _seed_published(db_session)
    live_version = article.published_version
    assert live_version is not None
    with TestClient(app) as client:
        _login(client)
        public = client.get(f"/api/v1/articles/{article.slug}")
        assert public.status_code == 200
        before = public.json()
        assert before["published_version"] == live_version
        assert any(item["id"] == str(claim.id) for item in before["claims"])
        history_types = {item["type"] for item in before["history"]}
        assert "published" in history_types
        assert "correction" not in history_types

        revised = _origin_post(
            client,
            f"/api/v1/admin/events/{event.id}/editorial-revise",
            json={
                "base_published_version": live_version,
                "kind": EditorialRevisionKind.CORRECTION.value,
                "headline": "La medida empieza en octubre",
                "summary": "Resumen",
                "body": "La medida comienza en octubre según el documento.\n\nCorregimos el segundo párrafo.",
                "public_notice": "La versión inicial indicaba que la medida regía desde septiembre. El documento oficial establece que comienza en octubre. Corregimos la fecha.",
                "show_near_title": True,
            },
        )
        assert revised.status_code == 200
        correction_id = revised.json()["correction_id"]
        assert correction_id

        conflict = _origin_post(
            client,
            f"/api/v1/admin/events/{event.id}/editorial-revise",
            json={
                "base_published_version": live_version,
                "kind": EditorialRevisionKind.MINOR.value,
                "headline": "La medida empieza en octubre",
                "summary": "Resumen",
                "body": "La medida comienza en octubre según el documento.\n\nCorregimos el segundo párrafo.",
            },
        )
        assert conflict.status_code == 409

        after = client.get(f"/api/v1/articles/{article.slug}").json()
        assert after["published_version"] == live_version + 1
        assert len([item for item in after["history"] if item["type"] == "correction"]) == 1
        assert not any(item["type"] == "pipeline_update" for item in after["history"])
        claim_ids = {item["id"] for item in after["claims"]}
        assert str(claim.id) in claim_ids
        blocks = after["body_blocks"]
        assert blocks[0]["segments"][0]["claim_ids"] == [str(claim.id)]
        assert blocks[1]["segments"][0]["claim_ids"] == []
        assert any(notice["show_near_title"] for notice in after["notices"])

        db_session.refresh(article)
        ArticleService(db_session).update_content(
            article,
            ArticleContentUpdate(
                headline="Draft pipeline",
                summary="Draft",
                body="Borrador nuevo del pipeline.",
                change_reason="material_change",
            ),
        )
        article.status = ArticleStatus.DRAFT
        db_session.commit()
        AuditService(
            db_session, llm=FakeStructuredLLM({"ArticleAuditResult": ArticleAuditResult(passed=True, issues=[])})
        ).audit(event.id, trigger="test")
        db_session.commit()

        denied = _origin_post(client, f"/api/v1/admin/events/{event.id}/publish")
        assert denied.status_code == 409
        assert denied.json()["detail"] == "editorial_hold"

        wrong = _origin_post(
            client,
            f"/api/v1/admin/events/{event.id}/publish",
            json={
                "override_editorial_hold": True,
                "target_version": 1,
                "base_published_version": live_version + 1,
            },
        )
        assert wrong.status_code == 409

        db_session.refresh(article)
        ok = _origin_post(
            client,
            f"/api/v1/admin/events/{event.id}/publish",
            json={
                "override_editorial_hold": True,
                "target_version": article.current_version,
                "base_published_version": article.published_version,
            },
        )
        assert ok.status_code == 200
        assert ok.json()["published"] is True
        assert ok.json().get("editorial_hold_override") is True
        still = client.get(f"/api/v1/articles/{article.slug}").json()
        assert any(item["type"] == "correction" for item in still["history"])

        created = client.post(
            "/api/v1/cases",
            headers={"Idempotency-Key": str(uuid4())},
            json={
                "article_id": str(article.id),
                "reported_version_number": live_version + 1,
                "reason": CaseReason.INCORRECT_FACT.value,
                "message": "Reporto la versión corregida para vincular la constancia publicada.",
            },
        )
        assert created.status_code == 201
        case_id = next(
            row["id"]
            for row in client.get("/api/v1/admin/cases").json()
            if row["public_code"] == created.json()["public_code"]
        )
        resolved = _origin_post(
            client,
            f"/api/v1/admin/cases/{case_id}/resolve",
            json={
                "outcome": CaseOutcome.CORRECTED.value,
                "public_resolution": "La fecha se corrigió según el documento oficial y quedó publicada.",
                "linked_correction_id": correction_id,
            },
        )
        assert resolved.status_code == 200


def test_forwarded_for_ignored_without_trusted_proxy(db_session: Session, monkeypatch) -> None:
    seen: list[str] = []

    def fake_allow(ip: str, article_id) -> bool:
        seen.append(ip)
        return True

    monkeypatch.setattr("app.api.cases.allow_case_submit", fake_allow)
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/cases",
            headers={"Idempotency-Key": str(uuid4()), "X-Forwarded-For": "203.0.113.9"},
            json={
                "reason": CaseReason.OTHER.value,
                "message": "Consulta general para probar que el forwarded-for no se usa solo.",
            },
        )
        assert created.status_code == 201
        assert seen
        assert seen[0] != "203.0.113.9"


def test_minor_has_no_public_notice(db_session: Session) -> None:
    event, article, _claim = _seed_published(db_session)
    result = EditorialService(db_session).revise(
        event.id,
        base_published_version=article.published_version or 1,
        kind=EditorialRevisionKind.MINOR,
        headline=article.headline,
        summary=article.summary,
        body=article.body + "\n\nAjuste de estilo.",
    )
    db_session.commit()
    assert result["correction_id"] is None
    with TestClient(app) as client:
        payload = client.get(f"/api/v1/articles/{article.slug}").json()
        assert payload["notices"] == []
        assert all(item["type"] != "correction" for item in payload["history"])
