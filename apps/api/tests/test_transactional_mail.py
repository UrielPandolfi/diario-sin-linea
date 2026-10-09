"""Verificación de email, restablecimiento y aviso de cambio de contraseña.

Los tests no llaman a Resend: el envío se reemplaza o el cliente HTTP es falso.
"""

from datetime import timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import utc_now
from app.core.config import get_settings
from app.main import app
from app.models.reader import Reader
from app.models.reader_email_verification import ReaderEmailVerification
from app.models.reader_password_reset import ReaderPasswordReset
from app.services.auth_tokens import hash_token
from app.services.mailer import from_header, mail_configured, mail_origin, origin_is_public, send_email
from tests.reader_session import authenticate_reader


def _clear_limits() -> None:
    from app.services.case_rate_limit import _redis_client

    with _redis_client() as client:
        for pattern in ("sin_linea:password-reset:*", "sin_linea:email-verification:*"):
            for key in client.scan_iter(pattern):
                client.delete(key)


class _Outbox:
    def __init__(self) -> None:
        self.messages: list[dict[str, str]] = []

    def send(self, _settings, *, to: str, subject: str, body: str, html: str | None = None) -> bool:
        self.messages.append({"to": to, "subject": subject, "body": body, "html": html or ""})
        return True

    def to(self, email: str) -> list[dict[str, str]]:
        return [message for message in self.messages if message["to"] == email]


def _token_from(body: str) -> str:
    return next(part.split("token=", 1)[1] for part in body.split() if "token=" in part)


def test_public_origin_rejects_localhost_and_preview_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    assert origin_is_public("https://www.sinlinea.ar") is True
    assert origin_is_public("https://sinlinea.ar") is True
    assert origin_is_public("http://www.sinlinea.ar") is False
    assert origin_is_public("https://localhost") is False
    assert origin_is_public("https://127.0.0.1") is False
    assert origin_is_public("https://diario-git-main.vercel.app") is False
    assert origin_is_public("https://web-production.up.railway.app") is False

    monkeypatch.setattr(settings, "app_base_url", "")
    monkeypatch.setattr(settings, "site_url", "http://localhost:3000")
    monkeypatch.setattr(settings, "resend_api_key", "re_test_key")
    monkeypatch.setattr(settings, "email_from", "no-reply@sinlinea.ar")
    assert mail_origin(settings) == "http://localhost:3000"
    assert mail_configured(settings) is False

    monkeypatch.setattr(settings, "app_base_url", "https://www.sinlinea.ar")
    monkeypatch.setattr(settings, "site_url", "http://localhost:3000")
    assert mail_origin(settings) == "https://www.sinlinea.ar"
    assert mail_configured(settings) is True
    assert from_header(settings) == "Sin Línea <no-reply@sinlinea.ar>"

    monkeypatch.setattr(settings, "resend_api_key", "")
    assert mail_configured(settings) is False


def test_send_email_uses_resend_and_does_not_log_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "resend_api_key", "re_test_key_not_real")
    monkeypatch.setattr(settings, "email_from", "no-reply@sinlinea.ar")
    monkeypatch.setattr(settings, "email_reply_to", "contacto@sinlinea.ar")
    monkeypatch.setattr(settings, "app_base_url", "https://www.sinlinea.ar")
    captured: list[tuple[str, dict, dict]] = []

    class FakeResponse:
        def __init__(self, status_code: int) -> None:
            self.status_code = status_code
            self.request = httpx.Request("POST", "https://api.resend.com/emails")

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise httpx.HTTPStatusError(
                    "rejected",
                    request=self.request,
                    response=httpx.Response(self.status_code, request=self.request),
                )

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            del args, kwargs

        def __enter__(self):
            return self

        def __exit__(self, *args) -> bool:
            del args
            return False

        def post(self, url, headers, json):
            captured.append((url, headers, json))
            return FakeResponse(200)

    notes: list[tuple] = []

    def spy_error(*args, **kwargs) -> None:
        del kwargs
        notes.append(args)

    monkeypatch.setattr("app.services.mailer.logger.error", spy_error)
    monkeypatch.setattr("app.services.mailer.httpx.Client", FakeClient)
    token = "token-que-no-puede-aparecer-en-logs"
    assert send_email(
        settings,
        to="lector@sinlinea.test",
        subject="Confirmá tu email",
        body=f"enlace https://www.sinlinea.ar/cuenta/verificar?token={token}\n",
        html=f"<a href='https://www.sinlinea.ar/cuenta/verificar?token={token}'>ir</a>",
    ) is True
    assert captured[0][0] == "https://api.resend.com/emails"
    assert captured[0][1]["Authorization"] == "Bearer re_test_key_not_real"
    assert captured[0][2]["from"] == "Sin Línea <no-reply@sinlinea.ar>"
    assert captured[0][2]["reply_to"] == "contacto@sinlinea.ar"
    assert captured[0][2]["to"] == ["lector@sinlinea.test"]
    assert notes == []

    class FailingClient(FakeClient):
        def post(self, url, headers, json):
            del url, headers, json
            return FakeResponse(422)

    monkeypatch.setattr("app.services.mailer.httpx.Client", FailingClient)
    assert send_email(settings, to="lector@sinlinea.test", subject="Aviso", body=token, html=token) is False
    logged = " ".join(str(part) for args in notes for part in args)
    assert "status=%s" in logged or "status=422" in logged
    assert token not in logged
    assert "re_test_key_not_real" not in logged


def test_register_verification_is_single_use_and_does_not_block_login(
    monkeypatch: pytest.MonkeyPatch, db_session: Session
) -> None:
    _clear_limits()
    outbox = _Outbox()
    settings = get_settings()
    monkeypatch.setattr(settings, "app_base_url", "https://www.sinlinea.ar")
    monkeypatch.setattr("app.api.auth.mail_configured", lambda _settings: True)
    monkeypatch.setattr("app.api.auth.send_email", outbox.send)
    email = "verificar@sinlinea.test"
    password = "clave-segura-1"
    with TestClient(app) as client:
        created = client.post("/api/v1/auth/register", json={"email": email, "password": password})
        assert created.status_code == 201
        assert created.json()["email_verified"] is False
        assert created.json()["email_verification"] == "sent"
        assert created.json()["email_verification_sent"] is True
        assert "sl_reader" in client.cookies
        assert client.get("/api/v1/auth/session").json()["authenticated"] is True
        logged = client.post("/api/v1/auth/login", json={"email": email, "password": password})
        assert logged.status_code == 200
        assert logged.json()["email_verified"] is False
        message = outbox.to(email)[0]
        assert message["body"].startswith("Confirmá tu email")
        assert "https://www.sinlinea.ar/cuenta/verificar?token=" in message["body"]
        assert "localhost" not in message["body"]
        assert password not in message["body"]
        assert password not in message["html"]
        token = _token_from(message["body"])
        stored = db_session.scalar(select(ReaderEmailVerification))
        assert stored is not None
        assert token not in stored.token_hash
        assert stored.token_hash == hash_token(token)
        confirmed = client.post("/api/v1/auth/email-verification/confirm", json={"token": token})
        assert confirmed.status_code == 200
        assert "eyJ" not in (confirmed.headers.get("set-cookie") or "")
        again = client.post("/api/v1/auth/email-verification/confirm", json={"token": token})
        assert again.status_code == 400
        session = client.get("/api/v1/auth/session").json()
        assert session["authenticated"] is True
        assert session["email_verified"] is True
    reader = db_session.scalar(select(Reader).where(Reader.email == email))
    assert reader is not None
    assert reader.email_verified_at is not None


def test_expired_verification_and_unknown_email_do_not_confirm(
    monkeypatch: pytest.MonkeyPatch, db_session: Session
) -> None:
    _clear_limits()
    outbox = _Outbox()
    monkeypatch.setattr(get_settings(), "app_base_url", "https://www.sinlinea.ar")
    monkeypatch.setattr("app.api.auth.mail_configured", lambda _settings: True)
    monkeypatch.setattr("app.api.auth.send_email", outbox.send)
    email = "vence-mail@sinlinea.test"
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": "clave-segura-1"},
        )
        assert created.status_code == 201
        token = _token_from(outbox.to(email)[0]["body"])
        row = db_session.scalar(
            select(ReaderEmailVerification).where(ReaderEmailVerification.token_hash == hash_token(token))
        )
        assert row is not None
        row.expires_at = utc_now() - timedelta(minutes=1)
        db_session.commit()
        expired = client.post("/api/v1/auth/email-verification/confirm", json={"token": token})
        assert expired.status_code == 400
        unknown = client.post(
            "/api/v1/auth/email-verification/request",
            json={"email": "nadie@sinlinea.test"},
        )
        known = client.post("/api/v1/auth/email-verification/request", json={"email": email})
        assert unknown.status_code == 200
        assert known.status_code == 200
        assert unknown.json() == known.json()
        assert "enviamos" not in unknown.json()["detail"]
        assert outbox.to("nadie@sinlinea.test") == []
        assert len(outbox.to(email)) == 2
    reader = db_session.scalar(select(Reader).where(Reader.email == email))
    assert reader is not None
    assert reader.email_verified_at is None


def test_verified_account_is_not_sent_another_link(monkeypatch: pytest.MonkeyPatch, db_session: Session) -> None:
    _clear_limits()
    outbox = _Outbox()
    monkeypatch.setattr("app.api.auth.mail_configured", lambda _settings: True)
    monkeypatch.setattr("app.api.auth.send_email", outbox.send)
    email = "ya-confirmado@sinlinea.test"
    with TestClient(app) as client:
        authenticate_reader(client, email=email)
        reader = db_session.scalar(select(Reader).where(Reader.email == email))
        assert reader is not None
        reader.email_verified_at = utc_now()
        db_session.commit()
        before = len(outbox.messages)
        asked = client.post("/api/v1/auth/email-verification/request", json={"email": email})
        missing = client.post(
            "/api/v1/auth/email-verification/request",
            json={"email": "otro-nadie@sinlinea.test"},
        )
        assert asked.status_code == 200
        assert asked.json() == missing.json()
        assert len(outbox.messages) == before
        logged = client.post("/api/v1/auth/login", json={"email": email, "password": "clave-segura-1"})
        assert logged.status_code == 200
        assert logged.json()["email_verified"] is True


def test_password_reset_does_not_open_a_session(monkeypatch: pytest.MonkeyPatch, db_session: Session) -> None:
    _clear_limits()
    outbox = _Outbox()
    monkeypatch.setattr(get_settings(), "app_base_url", "https://www.sinlinea.ar")
    monkeypatch.setattr("app.api.auth.mail_configured", lambda _settings: True)
    monkeypatch.setattr("app.api.auth.send_email", outbox.send)
    email = "reset-sesion@sinlinea.test"
    current = "clave-segura-1"
    new_password = "clave-nueva-22"
    with TestClient(app) as client:
        authenticate_reader(client, email=email, password=current)
        old_cookie = client.cookies.get("sl_reader")
        asked = client.post("/api/v1/auth/password-reset/request", json={"email": email})
        unknown = client.post("/api/v1/auth/password-reset/request", json={"email": "ausente-reset@sinlinea.test"})
        assert asked.status_code == 200
        assert asked.json() == unknown.json()
        assert outbox.to("ausente-reset@sinlinea.test") == []
        reset_message = next(message for message in outbox.to(email) if "/cuenta/restablecer?token=" in message["body"])
        token = _token_from(reset_message["body"])
        stored = db_session.scalar(select(ReaderPasswordReset).where(ReaderPasswordReset.token_hash == hash_token(token)))
        assert stored is not None
        assert token not in stored.token_hash
        changed = client.post(
            "/api/v1/auth/password-reset/confirm",
            json={"token": token, "password": new_password},
        )
        assert changed.status_code == 200
        cookie = changed.headers.get("set-cookie") or ""
        assert "Max-Age=0" in cookie
        assert "eyJ" not in cookie
        notice = outbox.to(email)[-1]
        assert new_password not in notice["body"]
        assert new_password not in notice["html"]
        assert current not in notice["body"]
        assert current not in notice["html"]
        assert token not in notice["body"]
        reused = client.post(
            "/api/v1/auth/password-reset/confirm",
            json={"token": token, "password": "clave-nueva-33"},
        )
        assert reused.status_code == 400
        client.cookies.set("sl_reader", old_cookie)
        assert client.get("/api/v1/auth/session").json()["authenticated"] is False
        logged = client.post("/api/v1/auth/login", json={"email": email, "password": new_password})
        assert logged.status_code == 200
    reader = db_session.scalar(select(Reader).where(Reader.email == email))
    assert reader is not None
    assert int(reader.session_generation) >= 1


def test_failed_delivery_does_not_claim_success_or_keep_the_token(
    monkeypatch: pytest.MonkeyPatch, db_session: Session
) -> None:
    _clear_limits()
    monkeypatch.setattr("app.api.auth.mail_configured", lambda _settings: True)
    monkeypatch.setattr("app.api.auth.send_email", lambda *_args, **_kwargs: False)
    email = "falla-mail@sinlinea.test"
    with TestClient(app) as client:
        created = client.post("/api/v1/auth/register", json={"email": email, "password": "clave-segura-1"})
        assert created.status_code == 201
        assert created.json()["email_verification"] == "failed"
        assert created.json()["email_verification_sent"] is False
        assert client.get("/api/v1/auth/session").json()["authenticated"] is True
        reset = client.post("/api/v1/auth/password-reset/request", json={"email": email})
        unknown = client.post("/api/v1/auth/password-reset/request", json={"email": "nadie-falla@sinlinea.test"})
        assert reset.status_code == 200
        assert reset.json() == unknown.json()
        assert "enviamos" not in reset.json()["detail"]
    reader = db_session.scalar(select(Reader).where(Reader.email == email))
    assert reader is not None
    assert db_session.scalar(select(ReaderEmailVerification).where(ReaderEmailVerification.reader_id == reader.id)) is None
    assert db_session.scalar(select(ReaderPasswordReset).where(ReaderPasswordReset.reader_id == reader.id)) is None


def test_password_change_notice_omits_the_secret(monkeypatch: pytest.MonkeyPatch, db_session: Session) -> None:
    del db_session
    _clear_limits()
    outbox = _Outbox()
    monkeypatch.setattr(get_settings(), "app_base_url", "https://www.sinlinea.ar")
    monkeypatch.setattr("app.api.auth.mail_configured", lambda _settings: True)
    monkeypatch.setattr("app.api.auth.send_email", outbox.send)
    email = "aviso@sinlinea.test"
    current = "clave-segura-1"
    new_password = "clave-nueva-22"
    with TestClient(app) as client:
        authenticate_reader(client, email=email, password=current)
        changed = client.post(
            "/api/v1/auth/password",
            json={"current_password": current, "new_password": new_password},
        )
        assert changed.status_code == 200
        assert changed.json()["security_notice_sent"] is True
        assert client.get("/api/v1/auth/session").json()["authenticated"] is True
    notice = outbox.to(email)[-1]
    assert "https://www.sinlinea.ar/cuenta/recuperar" in notice["body"]
    assert new_password not in notice["body"]
    assert new_password not in notice["html"]
    assert current not in notice["body"]
    assert "token=" not in notice["body"]


def test_verification_resend_is_rate_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_limits()
    monkeypatch.setattr("app.api.auth.mail_configured", lambda _settings: True)
    monkeypatch.setattr("app.api.auth.send_email", lambda *_args, **_kwargs: True)
    email = "cupo@sinlinea.test"
    with TestClient(app) as client:
        authenticate_reader(client, email=email)
        codes = [
            client.post("/api/v1/auth/email-verification/request", json={"email": email}).status_code
            for _ in range(4)
        ]
    assert codes[:3] == [200, 200, 200]
    assert codes[3] == 429
