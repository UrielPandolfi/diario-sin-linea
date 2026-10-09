from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.main import app
from app.models.reader import Reader
from app.services.reader_auth import issue_reader_token, read_reader_token
from tests.reader_session import authenticate_reader
from tests.test_public_api import _publish_passed, _seed

_VECTOR = "eyJleHAiOjE3MDAwMDAzMDAsInN1YiI6IjExMTExMTExLTExMTEtNDExMS04MTExLTExMTExMTExMTExMSJ9.6sMAInyt9h_J7aYFTaBfTldLe-1J9dRDU2srTf3d4S4"


def test_reader_token_matches_web_contract() -> None:
    token = issue_reader_token(
        "11111111-1111-4111-8111-111111111111",
        "dev-secret-change-me",
        now=1_700_000_000,
        ttl=300,
    )
    assert token == _VECTOR
    assert read_reader_token(token, "dev-secret-change-me", now=1_700_000_100) == "11111111-1111-4111-8111-111111111111"
    assert read_reader_token(token, "dev-secret-change-me", now=1_700_000_300) is None
    assert read_reader_token(token + "x", "dev-secret-change-me", now=1_700_000_100) is None


def test_register_login_logout_and_private_feed(db_session: Session) -> None:
    event, article = _seed(db_session, locality="Rosario", headline="Choque público Pellegrini", hash_key="authpub")
    _publish_passed(db_session, event)
    draft_event, draft = _seed(db_session, locality="Rosario", headline="Borrador secreto interno", hash_key="authdraft")
    db_session.commit()
    del draft_event

    with TestClient(app) as anon:
        feed = anon.get("/api/v1/feed")
        article_res = anon.get(f"/api/v1/articles/{article.slug}")
        missing = anon.get("/api/v1/articles/no-existe-esta-nota")
        draft_res = anon.get(f"/api/v1/articles/{draft.slug}")
        session = anon.get("/api/v1/auth/session")
    assert feed.status_code == 401
    assert feed.json()["detail"] == "No autenticado"
    assert "Choque público Pellegrini" not in feed.text
    assert "Borrador secreto interno" not in feed.text
    assert article_res.status_code == 200
    body = article_res.json()
    assert body["headline"] == "Choque público Pellegrini"
    assert body["published_version"] is not None
    assert "password_hash" not in body
    assert "email" not in body
    assert missing.status_code == 404
    assert draft_res.status_code == 404
    assert "Borrador secreto interno" not in draft_res.text
    assert session.json() == {"authenticated": False}

    with TestClient(app) as client:
        bad = client.post("/api/v1/auth/login", json={"email": "lector@sinlinea.test", "password": "clave-segura-1"})
        assert bad.status_code == 401
        assert "sl_reader" not in client.cookies

        created = client.post(
            "/api/v1/auth/register",
            json={"email": "Lector@SinLinea.test", "password": "clave-segura-1"},
        )
        assert created.status_code == 201
        assert created.json()["ok"] is True
        assert created.json()["email"] == "lector@sinlinea.test"
        assert created.json()["locality_step"] == "pending"
        assert created.json()["locality"] is None
        assert "password_hash" not in created.text
        assert "scrypt$" not in created.text
        duplicate = client.post(
            "/api/v1/auth/register",
            json={"email": "lector@sinlinea.test", "password": "clave-segura-1"},
        )
        assert duplicate.status_code == 409

        feed_ok = client.get("/api/v1/feed")
        assert feed_ok.status_code == 200
        assert feed_ok.headers["cache-control"] == "private, no-store"
        assert article.slug in {item["slug"] for item in feed_ok.json()["items"]}
        assert "email" not in feed_ok.json()
        assert client.get("/api/v1/auth/session").json()["email"] == "lector@sinlinea.test"

        logged_out = client.post("/api/v1/auth/logout")
        assert logged_out.status_code == 200
        assert client.get("/api/v1/feed").status_code == 401
        still_public = client.get(f"/api/v1/articles/{article.slug}")
        assert still_public.status_code == 200
        assert still_public.json()["headline"] == "Choque público Pellegrini"

        again = client.post("/api/v1/auth/login", json={"email": "lector@sinlinea.test", "password": "clave-segura-1"})
        assert again.status_code == 200
        assert client.get("/api/v1/feed").status_code == 200


def test_session_does_not_leak_another_reader(db_session: Session) -> None:
    del db_session
    with TestClient(app) as first, TestClient(app) as second:
        authenticate_reader(first, email="ana@sinlinea.test")
        authenticate_reader(second, email="bruno@sinlinea.test")
        ana = first.get("/api/v1/auth/session").json()
        bruno = second.get("/api/v1/auth/session").json()
        assert ana["authenticated"] is True and ana["email"] == "ana@sinlinea.test"
        assert bruno["authenticated"] is True and bruno["email"] == "bruno@sinlinea.test"
        assert ana["locality"] is None and bruno["locality"] is None
        assert first.get("/api/v1/feed").status_code == 200
        assert second.get("/api/v1/feed").status_code == 200


def test_deleted_reader_drops_the_signed_cookie(db_session: Session) -> None:
    with TestClient(app) as client:
        authenticate_reader(client, email="borrado@sinlinea.test")
        reader = db_session.scalar(select(Reader).where(Reader.email == "borrado@sinlinea.test"))
        assert reader is not None
        token = client.cookies.get("sl_reader")
        assert token
        live = client.get("/api/v1/auth/session")
        assert live.json()["authenticated"] is True
        assert "Max-Age=0" not in (live.headers.get("set-cookie") or "")
        db_session.delete(reader)
        db_session.commit()
        session = client.get("/api/v1/auth/session")
        assert session.status_code == 200
        assert session.json() == {"authenticated": False}
        assert "Max-Age=0" in (session.headers.get("set-cookie") or "")
        client.cookies.set("sl_reader", token)
        feed = client.get("/api/v1/feed")
        assert feed.status_code == 401
        assert feed.json()["detail"] == "No autenticado"
        assert "Max-Age=0" in (feed.headers.get("set-cookie") or "")


def test_expired_reader_session_can_still_read_a_published_article(db_session: Session) -> None:
    event, article = _seed(db_session, locality="Rosario", headline="Nota con sesión vencida", hash_key="authexp")
    _publish_passed(db_session, event)
    with TestClient(app) as client:
        authenticate_reader(client, email="vence@sinlinea.test")
        reader = db_session.scalar(select(Reader).where(Reader.email == "vence@sinlinea.test"))
        assert reader is not None
        expired = issue_reader_token(reader.id, get_settings().app_secret, now=1, ttl=10)
        client.cookies.set("sl_reader", expired)
        assert client.get("/api/v1/auth/session").json() == {"authenticated": False}
        assert client.get("/api/v1/feed").status_code == 401
        article_res = client.get(f"/api/v1/articles/{article.slug}")
        assert article_res.status_code == 200
        assert article_res.json()["slug"] == article.slug
