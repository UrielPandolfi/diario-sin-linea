from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.domain.enums import ArticleStatus, EventStatus
from app.main import app
from app.providers.fakes import FakeStructuredLLM
from app.schemas.auditing import ArticleAuditResult
from app.services.audit_service import AuditService
from tests.test_public_api import _publish_passed, _seed


def test_sitemap_articles_includes_published_and_excludes_drafts(db_session: Session) -> None:
    published_event, published = _seed(
        db_session, locality="Rosario", headline="Choque publicado", hash_key="sm-pub"
    )
    _draft_event, draft = _seed(db_session, locality="Rosario", headline="Borrador sitemap", hash_key="sm-draft")
    ready_event, ready = _seed(
        db_session, locality="Rosario", headline="Lista para revisar", hash_key="sm-ready"
    )
    archived_event, archived = _seed(
        db_session, locality="Rosario", headline="Archivada sitemap", hash_key="sm-arch"
    )
    _publish_passed(db_session, published_event)
    AuditService(
        db_session, llm=FakeStructuredLLM({"ArticleAuditResult": ArticleAuditResult(passed=True, issues=[])})
    ).audit(ready_event.id, trigger="test")
    _publish_passed(db_session, archived_event)
    db_session.refresh(archived)
    db_session.refresh(archived_event)
    archived.status = ArticleStatus.ARCHIVED
    archived_event.status = EventStatus.ARCHIVED
    db_session.commit()

    with TestClient(app) as client:
        response = client.get("/api/v1/sitemap-articles")
    assert response.status_code == 200
    payload = response.json()
    assert set(payload.keys()) == {"items"}
    slugs = {item["slug"] for item in payload["items"]}
    assert published.slug in slugs
    assert draft.slug not in slugs
    assert ready.slug not in slugs
    assert archived.slug not in slugs
    row = next(item for item in payload["items"] if item["slug"] == published.slug)
    assert set(row.keys()) == {"slug", "published_at", "updated_at"}
    assert row["published_at"]
    assert "body" not in row
    assert "headline" not in row
