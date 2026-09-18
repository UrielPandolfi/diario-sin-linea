from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from tests.origin import ADMIN_ORIGIN


def test_admin_sources_unauthorized_without_cookie() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/admin/sources")

    assert response.status_code == 401


def test_admin_login_then_list_sources() -> None:
    settings = get_settings()
    with TestClient(app) as client:
        login = client.post("/api/v1/admin/login", json={"password": settings.admin_password})
        assert login.status_code == 200
        assert login.json()["ok"] is True
        assert client.cookies.get("sl_admin")

        listed = client.get("/api/v1/admin/sources")
        assert listed.status_code == 200
        assert isinstance(listed.json(), list)


def test_ingestion_auto_poll_defaults_enabled() -> None:
    settings = get_settings()
    with TestClient(app) as client:
        client.post("/api/v1/admin/login", json={"password": settings.admin_password})
        response = client.get("/api/v1/admin/ingestion")
        stats = client.get("/api/v1/admin/stats")

    assert response.status_code == 200
    assert response.json() == {"auto_poll_enabled": True}
    assert stats.status_code == 200
    assert stats.json()["auto_poll_enabled"] is True


def test_ingestion_auto_poll_can_be_paused() -> None:
    settings = get_settings()
    with TestClient(app) as client:
        client.post("/api/v1/admin/login", json={"password": settings.admin_password})
        paused = client.patch(
            "/api/v1/admin/ingestion",
            json={"auto_poll_enabled": False},
            headers=ADMIN_ORIGIN,
        )
        fetched = client.get("/api/v1/admin/ingestion")
        stats = client.get("/api/v1/admin/stats")
        resumed = client.patch(
            "/api/v1/admin/ingestion",
            json={"auto_poll_enabled": True},
            headers=ADMIN_ORIGIN,
        )

    assert paused.status_code == 200
    assert paused.json() == {"auto_poll_enabled": False}
    assert fetched.json() == {"auto_poll_enabled": False}
    assert stats.json()["auto_poll_enabled"] is False
    assert resumed.json() == {"auto_poll_enabled": True}


def test_ingestion_auto_poll_patch_requires_origin() -> None:
    settings = get_settings()
    with TestClient(app) as client:
        client.post("/api/v1/admin/login", json={"password": settings.admin_password})
        response = client.patch("/api/v1/admin/ingestion", json={"auto_poll_enabled": False})

    assert response.status_code == 403
