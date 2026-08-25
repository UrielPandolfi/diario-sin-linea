from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.clock import utc_now
from app.core.config import get_settings
from app.domain.enums import ClaimImportance, ClaimStatus, EvidenceType, IngestionMethod
from app.main import app
from app.models import Claim, ClaimEvidence, Entity, EventEntity
from app.providers.fakes import FakeStructuredLLM
from app.schemas import ArticleCreate, EventCreate, SourceCreate, SourceItemCreate
from app.schemas.auditing import ArticleAuditResult
from app.services.article_service import ArticleService
from app.services.audit_service import AuditService
from app.services.event_service import EventService
from app.services.publish_service import PublishService
from app.services.source_item_service import SourceItemService
from app.services.source_service import SourceService
from app.domain.enums import EntityType


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


def _item(session: Session, source_id, *, url: str, title: str, body: str, content_hash: str):
    return SourceItemService(session).ingest(
        SourceItemCreate(
            source_id=source_id,
            url=url,
            canonical_url=url,
            content_hash=content_hash,
            title=title,
            clean_text=body,
        )
    ).item


def _seed(session: Session, *, locality: str, headline: str, hash_key: str, body: str | None = None):
    source = _source(
        session,
        name=f"Fuente {locality}",
        domain=f"{hash_key}.test",
        feed_url=f"https://{hash_key}.test/rss.xml",
    )
    text = body or f"{headline}. Un colectivo chocó."
    item = _item(session, source.id, url=f"https://{hash_key}.test/n", title=headline, body=text, content_hash=hash_key)
    event = EventService(session).create(
        EventCreate(
            title_internal=headline,
            event_type="accidente",
            source_item_id=item.id,
            started_at=datetime.now(timezone.utc),
            locality=locality,
            province="Santa Fe",
            short_summary=headline,
            relevance_score=70,
        )
    )
    claim = Claim(
        event_id=event.id,
        canonical_text=headline,
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
            excerpt=text[:40],
            source_url=item.url,
        )
    )
    article, _created = ArticleService(session).create_draft(
        ArticleCreate(event_id=event.id, headline=headline, summary=f"Resumen {locality}", body=text)
    )
    session.flush()
    return event, article


def _publish_passed(session: Session, event) -> None:
    AuditService(session, llm=FakeStructuredLLM({"ArticleAuditResult": ArticleAuditResult(passed=True, issues=[])})).audit(
        event.id, trigger="test"
    )
    PublishService(session).publish(event.id, trigger="test")
    session.commit()


def test_draft_and_ready_draft_absent_from_public_apis(db_session: Session) -> None:
    event, article = _seed(db_session, locality="Rosario", headline="Borrador Pellegrini", hash_key="draft")
    db_session.commit()
    with TestClient(app) as client:
        by_slug = client.get(f"/api/v1/articles/{article.slug}")
        feed = client.get("/api/v1/feed")
        live = client.get("/api/v1/live")
        now = client.get("/api/v1/now")
        local = client.get("/api/v1/local", params={"locality": "Rosario"})
        search = client.get("/api/v1/search", params={"q": "Pellegrini"})
    assert by_slug.status_code == 404
    for response in (feed, live, now, local, search):
        assert response.status_code == 200
        slugs = [item["slug"] for item in response.json()["items"]]
        assert article.slug not in slugs
    AuditService(
        db_session, llm=FakeStructuredLLM({"ArticleAuditResult": ArticleAuditResult(passed=True, issues=[])})
    ).audit(event.id, trigger="test")
    db_session.refresh(article)
    db_session.commit()
    with TestClient(app) as client:
        still = client.get(f"/api/v1/articles/{article.slug}")
        feed_after = client.get("/api/v1/feed")
    assert still.status_code == 404
    assert article.slug not in [item["slug"] for item in feed_after.json()["items"]]


def test_local_scope_filters_strictly_by_locality(db_session: Session) -> None:
    rosario, _article_r = _seed(db_session, locality="Rosario", headline="Choque en Rosario", hash_key="ros")
    cordoba, _article_c = _seed(db_session, locality="Córdoba", headline="Alerta en Córdoba", hash_key="cba")
    _publish_passed(db_session, rosario)
    _publish_passed(db_session, cordoba)
    db_session.refresh(_article_r)
    db_session.refresh(_article_c)
    with TestClient(app) as client:
        missing = client.get("/api/v1/feed", params={"scope": "local"})
        local_ros = client.get("/api/v1/local", params={"locality": "Rosario"})
        feed_local = client.get("/api/v1/feed", params={"scope": "local", "locality": "rosario"})
        feed_main = client.get("/api/v1/feed", params={"scope": "main", "locality": "Rosario"})
        nearby = client.get("/api/v1/nearby", params={"locality": "Rosario"})
    assert missing.status_code == 400
    ros_slugs = {item["slug"] for item in local_ros.json()["items"]}
    assert _article_r.slug in ros_slugs
    assert _article_c.slug not in ros_slugs
    assert {item["slug"] for item in feed_local.json()["items"]} == ros_slugs
    main_slugs = {item["slug"] for item in feed_main.json()["items"]}
    assert _article_r.slug in main_slugs
    assert _article_c.slug in main_slugs
    assert _article_r.slug in {item["slug"] for item in nearby.json()["items"]}
    assert _article_c.slug not in {item["slug"] for item in nearby.json()["items"]}


def test_search_skips_unpublished_and_finds_live_text(db_session: Session) -> None:
    draft_event, draft = _seed(db_session, locality="Rosario", headline="Secreto draft no indexar", hash_key="sec")
    pub_event, published = _seed(
        db_session,
        locality="Rosario",
        headline="Colectivos en Pellegrini",
        hash_key="pub",
        body="Dos colectivos chocaron en Pellegrini y Corrientes.",
    )
    entity = Entity(name="Pellegrini", normalized_name="pellegrini", entity_type=EntityType.PLACE)
    db_session.add(entity)
    db_session.flush()
    db_session.add(EventEntity(event_id=pub_event.id, entity_id=entity.id, role="lugar"))
    _publish_passed(db_session, pub_event)
    db_session.commit()
    with TestClient(app) as client:
        empty = client.get("/api/v1/search")
        found = client.get("/api/v1/search", params={"q": "colectivos"})
        by_entity = client.get("/api/v1/search", params={"q": "Pellegrini"})
        article = client.get(f"/api/v1/articles/{published.slug}")
        by_id = client.get(f"/api/v1/articles/{pub_event.public_id}")
        live = client.get("/api/v1/live")
        now = client.get("/api/v1/now")
        localities = client.get("/api/v1/localities")
    assert empty.status_code == 400
    slugs = {item["slug"] for item in found.json()["items"]}
    assert published.slug in slugs
    assert draft.slug not in slugs
    assert published.slug in {item["slug"] for item in by_entity.json()["items"]}
    assert article.status_code == 200
    assert article.json()["headline"] == "Colectivos en Pellegrini"
    assert article.json()["public_id"] == str(pub_event.public_id)
    assert by_id.status_code == 200
    assert by_id.json()["slug"] == published.slug
    assert published.slug in {item["slug"] for item in live.json()["items"]}
    assert now.json()["items"]
    assert "Rosario" in localities.json()["items"]
    assert draft_event.id


def test_nearby_respects_window(db_session: Session, monkeypatch) -> None:
    event, article = _seed(db_session, locality="Rosario", headline="Hecho viejo", hash_key="old")
    _publish_passed(db_session, event)
    db_session.refresh(article)
    article.published_at = utc_now() - timedelta(hours=48)
    event.last_material_update_at = article.published_at
    db_session.commit()
    settings = get_settings()
    monkeypatch.setattr(settings, "nearby_window_hours", 12)
    with TestClient(app) as client:
        nearby = client.get("/api/v1/nearby", params={"locality": "Rosario"})
        feed = client.get("/api/v1/feed", params={"scope": "local", "locality": "Rosario"})
    assert article.slug not in {item["slug"] for item in nearby.json()["items"]}
    assert article.slug in {item["slug"] for item in feed.json()["items"]}
