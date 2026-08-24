from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app


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
