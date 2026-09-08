from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.domain.enums import IngestionMethod, PipelineStatus, SourceItemStatus
from app.main import app
from app.models import PipelineRun
from app.schemas import SourceCreate, SourceItemCreate
from app.services.source_item_service import SourceItemService
from app.services.source_service import SourceService


def _login(client: TestClient) -> None:
    login = client.post("/api/v1/admin/login", json={"password": get_settings().admin_password})
    assert login.status_code == 200


def test_publications_list_uses_latest_detection_not_extracted_as_read(db_session: Session) -> None:
    source = SourceService(db_session).create(
        SourceCreate(
            name="Diario",
            preferred_ingestion_method=IngestionMethod.RSS,
            feed_url="https://d.test/rss",
            is_monitored=True,
            is_enabled=True,
        )
    )
    skipped = SourceItemService(db_session).ingest(
        SourceItemCreate(
            source_id=source.id,
            url="https://d.test/deporte",
            canonical_url="https://d.test/deporte",
            content_hash="dep",
            title="Final de fútbol",
            clean_text="Un summary RSS largo distinto del título del partido.",
            processing_status=SourceItemStatus.SKIPPED,
        )
    ).item
    skipped.metadata_json = {"body_source": "rss_summary", "fetch_ok": False}
    db_session.add(
        PipelineRun(
            source_item_id=skipped.id,
            stage="event_detection",
            status=PipelineStatus.SUCCESS,
            finished_at=datetime.now(timezone.utc),
            metadata_json={"filtered": True, "filter_reason": "SPORTS_ONLY"},
        )
    )
    db_session.commit()

    with TestClient(app) as client:
        _login(client)
        listed = client.get("/api/v1/admin/publications?limit=20")
        assert listed.status_code == 200
        body = listed.json()
        assert body["timestamp_field"] == "source_items.detected_at"
        row = next(item for item in body["items"] if item["id"] == str(skipped.id))
        assert row["outcome"] == "discarded"
        assert row["code"] == "SPORTS_ONLY"
        assert row["body_source"] == "rss_summary"
        assert "leída" not in (row.get("outcome_label") or "").lower()
        detail = client.get(f"/api/v1/admin/source-items/{skipped.id}")
        assert detail.status_code == 200
        payload = detail.json()
        assert payload["code"] == "SPORTS_ONLY"
        assert len(payload["pipeline_runs"]) == 1
        assert payload["pipeline_runs"][0]["detection"]["outcome"] == "discarded"


def test_detection_period_counts_attempts_and_unique_items(db_session: Session) -> None:
    source = SourceService(db_session).create(
        SourceCreate(
            name="Periodo",
            preferred_ingestion_method=IngestionMethod.RSS,
            feed_url="https://p.test/rss",
            is_monitored=True,
            is_enabled=True,
        )
    )
    item = SourceItemService(db_session).ingest(
        SourceItemCreate(
            source_id=source.id,
            url="https://p.test/n1",
            canonical_url="https://p.test/n1",
            content_hash="p1",
            title="Nota",
            clean_text="cuerpo",
        )
    ).item
    now = datetime.now(timezone.utc)
    db_session.add(
        PipelineRun(
            source_item_id=item.id,
            stage="event_detection",
            status=PipelineStatus.SUCCESS,
            started_at=now - timedelta(minutes=10),
            finished_at=now - timedelta(minutes=9),
            metadata_json={"filtered": True, "filter_reason": "SPORTS_ONLY"},
        )
    )
    db_session.add(
        PipelineRun(
            source_item_id=item.id,
            stage="event_detection",
            status=PipelineStatus.SUCCESS,
            started_at=now - timedelta(minutes=2),
            finished_at=now - timedelta(minutes=1),
            metadata_json={"created": False, "reason": "level1_url"},
        )
    )
    db_session.commit()

    with TestClient(app) as client:
        _login(client)
        stats = client.get("/api/v1/admin/stats")
        assert stats.status_code == 200
        detection = stats.json()["detection_24h"]
        assert detection["attempts"] >= 2
        assert detection["unique_items"] >= 1
        assert detection["attempts"] > detection["unique_items"]
        assert "discarded" in detection["by_outcome"]
        assert "linked" in detection["by_outcome"]
        assert "open_failure_count" in stats.json()
        assert "costs_24h" in stats.json()
        assert stats.json()["costs_24h"]["coverage"]["label"] in {"completo", "parcial"}

        runs = client.get("/api/v1/admin/detection-runs")
        assert runs.status_code == 200
        payload = runs.json()
        assert payload["attempts"] >= 2
        assert payload["unique_items"] >= 1
        item_runs = [row for row in payload["runs"] if row["source_item_id"] == str(item.id)]
        assert len(item_runs) == 2

        costs = client.get("/api/v1/admin/costs")
        assert costs.status_code == 200
        assert costs.json()["reconciliation"]["matches_global"] is True


def test_stats_separates_historical_error_from_open_failure(db_session: Session) -> None:
    source = SourceService(db_session).create(
        SourceCreate(
            name="Err",
            preferred_ingestion_method=IngestionMethod.RSS,
            feed_url="https://e.test/rss",
            is_monitored=True,
            is_enabled=True,
        )
    )
    item = SourceItemService(db_session).ingest(
        SourceItemCreate(
            source_id=source.id,
            url="https://e.test/n",
            canonical_url="https://e.test/n",
            content_hash="e1",
            title="Nota",
            clean_text="cuerpo",
        )
    ).item
    now = datetime.now(timezone.utc)
    db_session.add(
        PipelineRun(
            source_item_id=item.id,
            stage="event_detection",
            status=PipelineStatus.FAILED,
            error_message="boom antiguo",
            started_at=now - timedelta(minutes=10),
            finished_at=now - timedelta(minutes=9),
        )
    )
    db_session.add(
        PipelineRun(
            source_item_id=item.id,
            stage="event_detection",
            status=PipelineStatus.SUCCESS,
            started_at=now - timedelta(minutes=1),
            finished_at=now,
            metadata_json={"created": True, "reason": "no_candidates"},
        )
    )
    db_session.commit()

    with TestClient(app) as client:
        _login(client)
        stats = client.get("/api/v1/admin/stats")
        body = stats.json()
        assert body["last_failed_error"] == "boom antiguo"
        open_ids = {row["source_item_id"] for row in body["open_failures"]}
        assert str(item.id) not in open_ids


def test_linked_is_not_discarded_and_can_list_several_events(db_session: Session) -> None:
    from app.schemas import EventCreate
    from app.services.event_service import EventService

    source = SourceService(db_session).create(
        SourceCreate(
            name="Link",
            preferred_ingestion_method=IngestionMethod.RSS,
            feed_url="https://l.test/rss",
            is_monitored=True,
            is_enabled=True,
        )
    )
    item = SourceItemService(db_session).ingest(
        SourceItemCreate(
            source_id=source.id,
            url="https://l.test/n",
            canonical_url="https://l.test/n",
            content_hash="l1",
            title="Nota vinculada",
            clean_text="cuerpo",
            processing_status=SourceItemStatus.PROCESSED,
        )
    ).item
    event_a = EventService(db_session).create(
        EventCreate(title_internal="A", event_type="otro", source_item_id=item.id, short_summary="a")
    )
    event_b = EventService(db_session).create(
        EventCreate(title_internal="B", event_type="otro", source_item_id=item.id, short_summary="b")
    )
    db_session.add(
        PipelineRun(
            source_item_id=item.id,
            event_id=event_a.id,
            stage="event_detection",
            status=PipelineStatus.SUCCESS,
            finished_at=datetime.now(timezone.utc),
            metadata_json={"created": False, "reason": "level1_url"},
        )
    )
    db_session.commit()

    with TestClient(app) as client:
        _login(client)
        listed = client.get("/api/v1/admin/publications")
        row = next(item_row for item_row in listed.json()["items"] if item_row["id"] == str(item.id))
        assert row["outcome"] == "linked"
        assert row["code"] == "LEVEL1_URL"
        assert str(event_a.id) in row["event_ids"]
        assert str(event_b.id) in row["event_ids"]


def test_quota_skip_persists_pipeline_run(db_session: Session, monkeypatch) -> None:
    source = SourceService(db_session).create(
        SourceCreate(
            name="Cuota",
            preferred_ingestion_method=IngestionMethod.RSS,
            feed_url="https://q.test/rss",
            is_monitored=True,
            is_enabled=True,
        )
    )
    item = SourceItemService(db_session).ingest(
        SourceItemCreate(
            source_id=source.id,
            url="https://q.test/n",
            canonical_url="https://q.test/n",
            content_hash="q1",
            title="Nota",
            clean_text="cuerpo",
        )
    ).item
    db_session.commit()
    monkeypatch.setattr("app.workers.tasks.allow_new_event_pipeline", lambda poll_id: False)
    from sqlalchemy import select

    from app.workers.tasks import detect_event

    result = detect_event.run(str(item.id), "poll-q")
    assert result["pipeline_skipped"] is True
    db_session.expire_all()
    run = db_session.scalars(select(PipelineRun).where(PipelineRun.source_item_id == item.id)).first()
    assert run is not None
    assert run.metadata_json["reason"] == "max_new_events_per_poll"
    assert run.metadata_json["pipeline_skipped"] is True
