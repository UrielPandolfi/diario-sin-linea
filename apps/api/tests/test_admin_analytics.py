from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.clock import utc_now
from app.domain.enums import (
    ArticleStatus,
    ClaimImportance,
    ClaimStatus,
    EventStatus,
    EvidenceType,
    IngestionMethod,
    PipelineStatus,
    SourceItemStatus,
)
from app.main import app
from app.models import Claim, ClaimEvidence, PipelineRun
from app.schemas import ArticleCreate, EventCreate, SourceCreate, SourceItemCreate
from app.services.article_service import ArticleService
from app.services.event_service import EventService
from app.services.source_item_service import SourceItemService
from app.services.source_service import SourceService


def _login(client: TestClient) -> None:
    login = client.post("/api/v1/admin/login", json={"password": get_settings().admin_password})
    assert login.status_code == 200


def test_analytics_unauthorized_without_cookie() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/admin/analytics")
    assert response.status_code == 401


def test_analytics_read_only_snapshot_counts_existing_rows(db_session: Session) -> None:
    source = SourceService(db_session).create(
        SourceCreate(
            name="Diario",
            preferred_ingestion_method=IngestionMethod.RSS,
            feed_url="https://d.test/rss",
            is_monitored=True,
            is_enabled=True,
            domain="d.test",
        )
    )
    sports = SourceItemService(db_session).ingest(
        SourceItemCreate(
            source_id=source.id,
            url="https://d.test/deporte",
            canonical_url="https://d.test/deporte",
            content_hash="dep",
            title="Final de fútbol",
            clean_text="Un partido de fútbol.",
            processing_status=SourceItemStatus.SKIPPED,
        )
    ).item
    news = SourceItemService(db_session).ingest(
        SourceItemCreate(
            source_id=source.id,
            url="https://d.test/choque",
            canonical_url="https://d.test/choque",
            content_hash="cho",
            title="Choque en Pellegrini",
            clean_text="Un colectivo chocó en Pellegrini.",
        )
    ).item
    other = SourceItemService(db_session).ingest(
        SourceItemCreate(
            source_id=source.id,
            url="https://d.test/choque-b",
            canonical_url="https://d.test/choque-b",
            content_hash="chob",
            title="Otro recorte del choque",
            clean_text="Otra versión: no hubo heridos.",
        )
    ).item
    now = datetime.now(timezone.utc)
    db_session.add(
        PipelineRun(
            source_item_id=sports.id,
            stage="event_detection",
            status=PipelineStatus.SUCCESS,
            finished_at=now,
            metadata_json={"filtered": True, "filter_reason": "SPORTS_ONLY"},
        )
    )
    db_session.add(
        PipelineRun(
            source_item_id=news.id,
            stage="event_detection",
            status=PipelineStatus.SUCCESS,
            finished_at=now,
            metadata_json={"created": True, "reason": "no_candidates"},
        )
    )
    event = EventService(db_session).create(
        EventCreate(
            title_internal="Choque en Pellegrini",
            event_type="accidente",
            source_item_id=news.id,
            locality="Rosario",
            province="Santa Fe",
            short_summary="Un colectivo chocó en Rosario",
        )
    )
    event.status = EventStatus.PUBLISHED
    claim = Claim(
        event_id=event.id,
        canonical_text="Hubo heridos en el choque",
        claim_type="hecho",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.CONFLICTING,
    )
    db_session.add(claim)
    db_session.flush()
    db_session.add(
        ClaimEvidence(
            claim_id=claim.id,
            source_item_id=news.id,
            evidence_type=EvidenceType.SUPPORTS,
            excerpt="Hubo heridos en el choque",
            source_url=news.url,
        )
    )
    db_session.add(
        ClaimEvidence(
            claim_id=claim.id,
            source_item_id=other.id,
            evidence_type=EvidenceType.CONTRADICTS,
            excerpt="No hubo heridos",
            source_url=other.url,
        )
    )
    article, _created = ArticleService(db_session).create_draft(
        ArticleCreate(
            event_id=event.id,
            headline="Choque en Pellegrini",
            summary="Un colectivo chocó.",
            body="Un colectivo chocó en Pellegrini.",
        )
    )
    article.status = ArticleStatus.PUBLISHED
    article.published_version = 2
    article.current_version = 2
    article.published_at = utc_now()
    db_session.add(
        PipelineRun(
            event_id=event.id,
            stage="writing",
            status=PipelineStatus.SUCCESS,
            finished_at=now,
            metadata_json={"material_reasons": ["new_high_claim"]},
        )
    )
    db_session.commit()

    with TestClient(app) as client:
        _login(client)
        response = client.get("/api/v1/admin/analytics?window=all")

    assert response.status_code == 200
    payload = response.json()
    assert payload["read_only"] is True
    assert payload["funnel"]["notes_ingested"] >= 3
    assert payload["funnel"]["notes_discarded_not_news"] >= 1
    assert payload["funnel"]["sucesos_created"] >= 1
    assert payload["funnel"]["articles_published"] >= 1
    assert payload["funnel"]["articles_updated_track_b"] >= 1
    discarded = {row["code"]: row for row in payload["detection"]["discarded_codes"]}
    assert "SPORTS_ONLY" in discarded
    labels = {row["key"]: row["count"] for row in payload["editorial_labels"]["on_articles"]}
    assert labels["DISCREPANCY"] >= 1
    assert any("discrepancias entre medios" in line for line in payload["headline"])
    assert payload["publication"]["writing_material_updates"] >= 1
