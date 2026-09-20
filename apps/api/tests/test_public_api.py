from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
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
from app.services.hero_image_service import HeroImageService
from app.services.source_item_service import SourceItemService
from app.services.source_service import SourceService
from app.domain.enums import EntityType
from tests.editorial_snapshot import persist_version_snapshot


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
    persist_version_snapshot(session, event, article)
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
    assert article.json()["hero_image_url"]
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


def test_public_article_tolerates_null_hero(db_session: Session, monkeypatch) -> None:
    def boom(self, article_id):
        raise IntegrityError("INSERT", {}, Exception("hero flush"))

    monkeypatch.setattr(HeroImageService, "persist", boom)
    event, article = _seed(db_session, locality="Rosario", headline="Sin portada", hash_key="nohero")
    _publish_passed(db_session, event)
    with TestClient(app) as client:
        payload = client.get(f"/api/v1/articles/{article.slug}")
    assert payload.status_code == 200
    assert payload.json()["hero_image_url"] is None


def test_public_article_claims_follow_published_snapshot_not_live_verify(db_session: Session) -> None:
    from app.schemas.editorial_evidence import Demotion
    from tests.test_editorial_label_policy import _later_live_supported, _publish_with_snapshot_decision

    event, article, claim, _snap = _publish_with_snapshot_decision(
        db_session,
        hash_key="pubc2",
        decision={
            "status": ClaimStatus.SINGLE_SOURCE.value,
            "unresolved": False,
            "evaluation_state": "complete",
            "llm_reason": None,
            "support_basis": {
                "known_independent_count": 1,
                "unknown_group_count": 0,
                "documents_consulted": 1,
                "documents_supporting": 1,
                "demotion": Demotion.INSUFFICIENT_INDEPENDENCE.value,
                "kind": "single_report",
            },
        },
    )
    cid = str(claim.id)
    extra = Claim(
        event_id=event.id,
        canonical_text="El expediente ya tiene fecha de audiencia",
        claim_type="hecho",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.SUPPORTED,
    )
    db_session.add(extra)
    db_session.flush()
    _later_live_supported(db_session, event, claim)
    db_session.commit()
    with TestClient(app) as client:
        payload = client.get(f"/api/v1/articles/{article.slug}").json()
        feed = client.get("/api/v1/feed").json()
    assert payload["published_version"] == 1
    public_ids = {row["id"] for row in payload["claims"]}
    assert public_ids == {cid}
    assert str(extra.id) not in public_ids
    row = payload["claims"][0]
    assert row["status"] == ClaimStatus.SINGLE_SOURCE.value
    assert row["presentation"]["verification_label"] == "Respaldo limitado"
    assert row["presentation"]["known_independent_count"] == 1
    assert "demotion" not in row["presentation"]
    assert "llm_reason" not in row
    from app.services.claim_card_presentation import public_copy_has_technical_tokens
    from app.services.claim_card_presentation import ClaimCardPresentation
    card = ClaimCardPresentation.model_validate(row["presentation"])
    assert not public_copy_has_technical_tokens(card)
    assert "CHECKED" not in row["editorial_labels"]
    feed_item = next(item for item in feed["items"] if item["slug"] == article.slug)
    assert "claims" not in feed_item
    assert "presentation" not in feed_item
