from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.domain.enums import IngestionMethod, SourceItemStatus
from app.main import app
from app.schemas import SourceCreate, SourceItemCreate
from app.services.source_item_service import SourceItemService
from app.services.source_service import SourceService


def test_requeue_pending_enqueues_detection(db_session: Session, monkeypatch) -> None:
    queued: list[tuple] = []
    monkeypatch.setattr("app.api.admin.detect_event.delay", lambda *args: queued.append(args))
    source = SourceService(db_session).create(
        SourceCreate(
            name="Fuente",
            preferred_ingestion_method=IngestionMethod.RSS,
            feed_url="https://ejemplo.test/rss.xml",
            is_monitored=True,
            is_enabled=True,
        )
    )
    for index in range(5):
        SourceItemService(db_session).ingest(
            SourceItemCreate(
                source_id=source.id,
                url=f"https://ejemplo.test/n{index}",
                canonical_url=f"https://ejemplo.test/n{index}",
                content_hash=f"h{index}",
                title=f"Nota {index}",
                clean_text="texto",
                processing_status=SourceItemStatus.PENDING,
            )
        )
    db_session.commit()
    settings = get_settings()
    with TestClient(app) as client:
        client.post("/api/v1/admin/login", json={"password": settings.admin_password})
        response = client.post("/api/v1/admin/source-items/requeue-pending?limit=3")
    assert response.status_code == 202
    body = response.json()
    assert body["queued"] == 3
    assert len(queued) == 3
    assert body["poll_id"]
    assert all(len(args) == 2 for args in queued)


def test_requeue_pending_empty(db_session: Session, monkeypatch) -> None:
    queued: list[tuple] = []
    monkeypatch.setattr("app.api.admin.detect_event.delay", lambda *args: queued.append(args))
    db_session.commit()
    settings = get_settings()
    with TestClient(app) as client:
        client.post("/api/v1/admin/login", json={"password": settings.admin_password})
        response = client.post("/api/v1/admin/source-items/requeue-pending?limit=3")
    assert response.status_code == 202
    assert response.json()["queued"] == 0
    assert queued == []
