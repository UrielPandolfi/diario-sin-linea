"""Contraseña de admin, recuperación, actualizaciones públicas y etiquetas de fuente."""

from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.admin_secret import admin_passwords_match, assert_admin_password
from app.core.clock import utc_now
from app.core.config import get_settings
from app.domain.enums import CaseReason, PipelineStatus
from app.main import app
from app.models import ArticleVersion, EventUpdate, PipelineRun, Reader
from app.models.reader_case import ReaderCase
from app.services.public_updates import material_notice
from app.services.source_labels import public_source_name, public_source_title
from tests.reader_session import authenticate_reader
from tests.test_public_api import _publish_passed, _seed

AUDITING = "auditing"


def _clear_reset_limits() -> None:
    from app.services.case_rate_limit import _redis_client

    with _redis_client() as client:
        for key in client.scan_iter("sin_linea:password-reset:*"):
            client.delete(key)


def test_dev_admin_password_is_rejected() -> None:
    with pytest.raises(RuntimeError):
        assert_admin_password("dev-admin")
    with pytest.raises(RuntimeError):
        assert_admin_password("")
    with pytest.raises(RuntimeError):
        assert_admin_password("x" * 31)
    assert_admin_password("x" * 32)


def test_admin_password_compare_ignores_length_difference() -> None:
    expected = "x" * 40
    assert admin_passwords_match(expected, expected) is True
    assert admin_passwords_match("dev-admin", expected) is False
    assert admin_passwords_match("", expected) is False


def test_reader_cannot_use_admin_and_old_password_fails(db_session: Session) -> None:
    del db_session
    settings = get_settings()
    original = settings.admin_password
    with TestClient(app) as client:
        authenticate_reader(client, email="admin-gate@sinlinea.test")
        assert client.get("/api/v1/admin/me").status_code == 401
        assert client.post("/api/v1/admin/login", json={"password": "dev-admin"}).status_code == 401
        login = client.post("/api/v1/admin/login", json={"password": original})
        assert login.status_code == 200
        assert client.get("/api/v1/admin/me").status_code == 200
        settings.admin_password = "otra-contrasena-de-admin-larga-000000"
        try:
            assert client.get("/api/v1/admin/me").status_code == 401
        finally:
            settings.admin_password = original


def test_password_reset_does_not_reveal_the_account(monkeypatch, db_session: Session) -> None:
    _clear_reset_limits()
    monkeypatch.setattr("app.api.auth.mail_configured", lambda _settings: False)
    with TestClient(app) as client:
        authenticate_reader(client, email="reset-oculto@sinlinea.test", password="clave-segura-1")
        known = client.post("/api/v1/auth/password-reset/request", json={"email": "reset-oculto@sinlinea.test"})
        unknown = client.post("/api/v1/auth/password-reset/request", json={"email": "nadie@sinlinea.test"})
    assert known.status_code == 503
    assert unknown.status_code == 503
    assert known.json()["detail"] == unknown.json()["detail"]
    assert db_session.scalar(select(Reader).where(Reader.email == "reset-oculto@sinlinea.test")) is not None


def test_password_reset_is_single_use_and_closes_old_sessions(monkeypatch, db_session: Session) -> None:
    sent: dict[str, str] = {}

    def send(_settings, *, to: str, subject: str, body: str) -> bool:
        del subject
        sent[to] = body
        return True

    _clear_reset_limits()
    monkeypatch.setattr("app.api.auth.mail_configured", lambda _settings: True)
    monkeypatch.setattr("app.api.auth.send_email", send)
    email = "reset-uso@sinlinea.test"
    with TestClient(app) as client:
        authenticate_reader(client, email=email, password="clave-segura-1")
        old_cookie = client.cookies.get("sl_reader")
        missing = client.post("/api/v1/auth/password-reset/request", json={"email": "ausente@sinlinea.test"})
        assert missing.status_code == 200
        assert "ausente@sinlinea.test" not in sent
        asked = client.post("/api/v1/auth/password-reset/request", json={"email": email})
        assert asked.status_code == 200
        assert asked.json()["detail"] == missing.json()["detail"]
        link = sent[email].split()
        token = next(part.split("token=", 1)[1] for part in link if "token=" in part)
        changed = client.post(
            "/api/v1/auth/password-reset/confirm",
            json={"token": token, "password": "clave-nueva-22"},
        )
        assert changed.status_code == 200
        again = client.post(
            "/api/v1/auth/password-reset/confirm",
            json={"token": token, "password": "clave-nueva-33"},
        )
        assert again.status_code == 400
        client.cookies.set("sl_reader", old_cookie)
        session = client.get("/api/v1/auth/session")
        assert session.json()["authenticated"] is False
        logged = client.post("/api/v1/auth/login", json={"email": email, "password": "clave-nueva-22"})
        assert logged.status_code == 200
    reader = db_session.scalar(select(Reader).where(Reader.email == email))
    assert reader is not None
    assert int(reader.session_generation) >= 1


def test_profile_password_change_checks_the_current_one() -> None:
    email = "cambio@sinlinea.test"
    with TestClient(app) as client:
        authenticate_reader(client, email=email, password="clave-segura-1")
        old_cookie = client.cookies.get("sl_reader")
        wrong = client.post(
            "/api/v1/auth/password",
            json={"current_password": "no-es", "new_password": "clave-nueva-22"},
        )
        assert wrong.status_code == 401
        changed = client.post(
            "/api/v1/auth/password",
            json={"current_password": "clave-segura-1", "new_password": "clave-nueva-22"},
        )
        assert changed.status_code == 200
        client.cookies.set("sl_reader", old_cookie)
        assert client.get("/api/v1/auth/session").json()["authenticated"] is False


def test_deletion_request_creates_a_case_and_keeps_the_reader(db_session: Session) -> None:
    email = "baja@sinlinea.test"
    with TestClient(app) as client:
        authenticate_reader(client, email=email)
        denied = client.post("/api/v1/auth/deletion-request", json={"message": "corto"})
        assert denied.status_code == 422
        created = client.post(
            "/api/v1/auth/deletion-request",
            json={"message": "Quiero eliminar esta cuenta y los datos asociados a este email."},
        )
        assert created.status_code == 201
        body = created.json()
        assert body["public_code"]
        assert body["follow_up_url"].startswith("/seguimiento/")
    reader = db_session.scalar(select(Reader).where(Reader.email == email))
    assert reader is not None
    case = db_session.scalar(select(ReaderCase).where(ReaderCase.email == email))
    assert case is not None
    assert case.reason == CaseReason.ACCOUNT_DELETION


def test_source_labels_keep_the_real_name_and_drop_garbage() -> None:
    assert public_source_name("staging.clarin.com", "staging.clarin.com") == "clarin.com"
    assert public_source_name("Clarín", "staging.clarin.com") == "Clarín"
    assert public_source_name(None, None) == "Publicación"
    assert public_source_title("‰8s!-zècQ|1Š") is None
    assert public_source_title("Fallo de la Cámara") == "Fallo de la Cámara"


def test_material_notice_names_what_changed() -> None:
    previous = ArticleVersion(
        article_id=uuid4(),
        version_number=1,
        headline="Titular",
        summary="Bajada",
        body="Texto",
    )
    same = ArticleVersion(
        article_id=previous.article_id,
        version_number=2,
        headline="Titular",
        summary="Bajada",
        body="Texto",
    )
    changed = ArticleVersion(
        article_id=previous.article_id,
        version_number=3,
        headline="Titular nuevo",
        summary="Bajada",
        body="Texto",
    )
    assert material_notice(previous, same) is None
    assert material_notice(previous, changed) == "Actualización: cambió el titular."


def _clone_published_version(session: Session, article, *, headline: str | None = None) -> ArticleVersion:
    live = session.scalar(
        select(ArticleVersion).where(
            ArticleVersion.article_id == article.id,
            ArticleVersion.version_number == article.published_version,
        )
    )
    assert live is not None
    number = int(article.current_version) + 1
    created = ArticleVersion(
        article_id=article.id,
        version_number=number,
        headline=headline or live.headline,
        summary=live.summary,
        body=live.body,
        body_blocks=live.body_blocks,
    )
    session.add(created)
    article.current_version = number
    article.headline = created.headline
    run = session.scalar(
        select(PipelineRun)
        .where(PipelineRun.event_id == article.event_id, PipelineRun.stage == AUDITING)
        .order_by(PipelineRun.started_at.desc())
    )
    assert run is not None
    meta = dict(run.metadata_json or {})
    meta["version_after"] = number
    snapshot = dict(meta.get("evidence_snapshot") or {})
    snapshot["version"] = number
    meta["evidence_snapshot"] = snapshot
    session.add(
        PipelineRun(
            event_id=article.event_id,
            stage=AUDITING,
            status=PipelineStatus.SUCCESS,
            started_at=utc_now() + timedelta(seconds=5),
            finished_at=utc_now() + timedelta(seconds=5),
            metadata_json=meta,
        )
    )
    session.commit()
    return created


def test_identical_republish_does_not_look_like_a_new_fact(db_session: Session) -> None:
    event, article = _seed(db_session, locality="Rosario", headline="Hecho único", hash_key="hecho-unico")
    _publish_passed(db_session, event)
    db_session.refresh(article)
    db_session.refresh(event)
    before = event.last_material_update_at
    _clone_published_version(db_session, article)
    from app.services.publish_service import PublishService

    result = PublishService(db_session).publish(event.id, trigger="test")
    db_session.commit()
    db_session.refresh(event)
    assert result["published"] is True
    assert result["first_publish"] is False
    assert event.last_material_update_at == before
    rows = list(
        db_session.scalars(
            select(EventUpdate).where(EventUpdate.event_id == event.id).order_by(EventUpdate.occurred_at.asc())
        )
    )
    assert rows[-1].is_material is False
    with TestClient(app) as client:
        authenticate_reader(client)
        now = client.get("/api/v1/now")
    matches = [item for item in now.json()["items"] if item["slug"] == article.slug]
    assert len(matches) == 1
    assert matches[0]["notice"] is None


def test_material_republish_explains_the_change(db_session: Session) -> None:
    event, article = _seed(db_session, locality="Rosario", headline="Hecho que cambia", hash_key="hecho-cambia")
    _publish_passed(db_session, event)
    db_session.refresh(article)
    _clone_published_version(db_session, article, headline="Hecho que cambia de verdad")
    from app.services.publish_service import PublishService

    result = PublishService(db_session).publish(event.id, trigger="test")
    db_session.commit()
    db_session.refresh(event)
    assert result["published"] is True
    assert event.last_material_update_at is not None
    with TestClient(app) as client:
        authenticate_reader(client)
        now = client.get("/api/v1/now")
        article_response = client.get(f"/api/v1/articles/{article.slug}")
    matches = [item for item in now.json()["items"] if item["slug"] == article.slug]
    assert any(item["notice"] == "Actualización: cambió el titular." for item in matches)
    history = [item for item in article_response.json()["history"] if item["type"] == "pipeline_update"]
    assert any(item["notice"] == "Actualización: cambió el titular." for item in history)


def test_failed_reset_mail_does_not_leave_a_token(monkeypatch, db_session: Session) -> None:
    _clear_reset_limits()
    monkeypatch.setattr("app.api.auth.mail_configured", lambda _settings: True)
    monkeypatch.setattr("app.api.auth.send_email", lambda *_args, **_kwargs: False)
    monkeypatch.setattr("app.api.auth.allow_password_reset", lambda *_args, **_kwargs: True)
    email = "reset-falla@sinlinea.test"
    with TestClient(app) as client:
        authenticate_reader(client, email=email)
        response = client.post("/api/v1/auth/password-reset/request", json={"email": email})
        unknown = client.post("/api/v1/auth/password-reset/request", json={"email": "otro-ausente@sinlinea.test"})
    assert response.status_code == 200
    assert unknown.status_code == 200
    assert response.json() == unknown.json()
    reader = db_session.scalar(select(Reader).where(Reader.email == email))
    assert reader is not None
    from app.models.reader_password_reset import ReaderPasswordReset

    leftover = db_session.scalar(select(ReaderPasswordReset).where(ReaderPasswordReset.reader_id == reader.id))
    assert leftover is None
