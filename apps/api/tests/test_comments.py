from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import utc_now
from app.main import app
from app.models.reader import Reader
from app.models.reader_avatar import ReaderAvatar
from app.services.avatar_service import AvatarService, request_reader_avatar
from app.services.email_verification import issue_verification
from app.services.hero_image_error import HeroImageError
from tests.reader_session import authenticate_reader
from tests.test_public_api import _publish_passed, _seed


def _png() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (16, 16), (12, 34, 56)).save(buffer, format="PNG")
    return buffer.getvalue()


class _Images:
    def generate_avatar(self, prompt: str, *, seed: int) -> bytes:
        del prompt, seed
        return _png()


class _FailingImages:
    def generate_avatar(self, prompt: str, *, seed: int) -> bytes:
        del prompt, seed
        raise HeroImageError("replicate_error", "No se pudo generar la imagen", 502)


def test_username_is_unique_and_normalized(db_session: Session) -> None:
    del db_session
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/auth/register",
            json={"email": "uno@sinlinea.test", "password": "clave-segura-1", "username": "Repetido"},
        )
        assert created.status_code == 201
        assert created.json()["username"] == "repetido"
        taken = client.post(
            "/api/v1/auth/register",
            json={"email": "dos@sinlinea.test", "password": "clave-segura-1", "username": "repetido"},
        )
        assert taken.status_code == 409
        assert taken.json()["detail"] == "Ese nombre de usuario ya está en uso"
        invalid = client.post(
            "/api/v1/auth/register",
            json={"email": "tres@sinlinea.test", "password": "clave-segura-1", "username": "no-vale"},
        )
        assert invalid.status_code == 422


def test_comment_policy(monkeypatch: pytest.MonkeyPatch, db_session: Session) -> None:
    monkeypatch.setattr("app.api.comments.allow_comment", lambda *_args, **_kwargs: True)
    event, article = _seed(db_session, locality="Rosario", headline="Nota con comentarios", hash_key="comentarios")
    _publish_passed(db_session, event)
    _draft_event, draft = _seed(db_session, locality="Rosario", headline="Borrador sin comentarios", hash_key="comentdraft")
    db_session.commit()

    with TestClient(app) as anon:
        assert anon.get(f"/api/v1/articles/{draft.slug}/comments").status_code == 404
        empty = anon.get(f"/api/v1/articles/{article.slug}/comments")
        assert empty.status_code == 200
        assert empty.json() == {"items": []}
        assert anon.post(f"/api/v1/articles/{article.slug}/comments", json={"body": "sin sesión"}).status_code == 401

    email = "comenta@sinlinea.test"
    with TestClient(app) as client:
        authenticate_reader(client, email=email)
        blocked = client.post(f"/api/v1/articles/{article.slug}/comments", json={"body": "todavía no"})
        assert blocked.status_code == 403
        assert blocked.json()["detail"] == "email_not_verified"

        reader = db_session.scalar(select(Reader).where(Reader.email == email))
        assert reader is not None
        reader.email_verified_at = utc_now()
        reader.username = None
        db_session.commit()
        nameless = client.post(f"/api/v1/articles/{article.slug}/comments", json={"body": "sin nombre"})
        assert nameless.status_code == 403
        assert nameless.json()["detail"] == "username_required"
        chosen = client.put("/api/v1/auth/username", json={"username": "Comenta_1"})
        assert chosen.status_code == 200
        assert chosen.json()["username"] == "comenta_1"
        assert client.put("/api/v1/auth/username", json={"username": "otro_nombre"}).status_code == 409

        blank = client.post(f"/api/v1/articles/{article.slug}/comments", json={"body": "   "})
        assert blank.status_code == 422
        assert blank.json()["detail"] == "comment_invalid"

        created = client.post(f"/api/v1/articles/{article.slug}/comments", json={"body": "primera"})
        assert created.status_code == 201
        assert created.json()["author"]["username"] == "comenta_1"
        assert created.json()["anonymous"] is False
        root_id = created.json()["id"]

        AvatarService(db_session, images=_Images()).generate(reader.id)
        db_session.commit()
        named = client.post(f"/api/v1/articles/{article.slug}/comments", json={"body": "con foto"})
        assert named.status_code == 201
        assert named.json()["author"]["avatar_url"]
        assert str(reader.id) in named.json()["author"]["avatar_url"]

        hidden = client.post(
            f"/api/v1/articles/{article.slug}/comments",
            json={"body": "en secreto", "anonymous": True},
        )
        assert hidden.status_code == 201
        assert hidden.json()["anonymous"] is True
        assert hidden.json()["author"] is None
        hidden_dump = hidden.text
        assert "comenta_1" not in hidden_dump
        assert "avatar" not in hidden_dump
        assert str(reader.id) not in hidden_dump
        assert email not in hidden_dump

        reply = client.post(
            f"/api/v1/articles/{article.slug}/comments",
            json={"body": "respuesta", "parent_id": root_id},
        )
        assert reply.status_code == 201
        nested = client.post(
            f"/api/v1/articles/{article.slug}/comments",
            json={"body": "demasiado profundo", "parent_id": reply.json()["id"]},
        )
        assert nested.status_code == 400
        assert nested.json()["detail"] == "reply_not_root"

    with TestClient(app) as public:
        listed = public.get(f"/api/v1/articles/{article.slug}/comments")
        assert listed.status_code == 200
        assert "sl_reader" not in public.cookies
        items = listed.json()["items"]
        assert [item["body"] for item in items] == ["primera", "con foto", "en secreto"]
        assert items[0]["replies"][0]["body"] == "respuesta"
        assert "replies" not in items[0]["replies"][0]
        secret = items[2]
        assert secret["author"] is None
        secret_dump = str(secret)
        assert "comenta_1" not in secret_dump
        assert "avatar" not in secret_dump
        assert str(reader.id) not in secret_dump
        assert email not in secret_dump
        assert items[1]["author"]["username"] == "comenta_1"
        assert items[1]["author"]["avatar_url"]


def test_avatar_failure_keeps_email_verified(monkeypatch: pytest.MonkeyPatch, db_session: Session) -> None:
    email = "foto@sinlinea.test"
    with TestClient(app) as client:
        authenticate_reader(client, email=email)
        reader = db_session.scalar(select(Reader).where(Reader.email == email))
        assert reader is not None
        assert reader.email_verified_at is None
        token = issue_verification(db_session, reader)
        db_session.commit()

        def boom(reader_id: object) -> None:
            del reader_id
            raise RuntimeError("broker")

        monkeypatch.setattr("app.services.avatar_service.enqueue_reader_avatar", boom)
        confirmed = client.post("/api/v1/auth/email-verification/confirm", json={"token": token})
        assert confirmed.status_code == 200

    db_session.expire_all()
    reader = db_session.scalar(select(Reader).where(Reader.email == email))
    assert reader is not None
    assert reader.email_verified_at is not None
    assert reader.avatar_enqueued_at is None
    assert db_session.get(ReaderAvatar, reader.id) is None

    with pytest.raises(HeroImageError):
        AvatarService(db_session, images=_FailingImages()).generate(reader.id)
    db_session.rollback()
    db_session.expire_all()
    reader = db_session.scalar(select(Reader).where(Reader.email == email))
    assert reader is not None
    assert reader.email_verified_at is not None
    assert db_session.get(ReaderAvatar, reader.id) is None


def test_session_asks_for_a_missing_avatar_without_calling_replicate(
    monkeypatch: pytest.MonkeyPatch, db_session: Session
) -> None:
    called = {"enqueue": 0}

    def mark(reader_id: object) -> None:
        del reader_id
        called["enqueue"] += 1

    monkeypatch.setattr("app.services.avatar_service.enqueue_reader_avatar", mark)
    email = "yaverificado@sinlinea.test"
    with TestClient(app) as client:
        authenticate_reader(client, email=email)
        reader = db_session.scalar(select(Reader).where(Reader.email == email))
        assert reader is not None
        reader.email_verified_at = utc_now()
        db_session.commit()
        session = client.get("/api/v1/auth/session")
        assert session.status_code == 200
        assert session.json()["email_verified"] is True
        assert session.json()["avatar_url"] is None
    assert called["enqueue"] == 1
    db_session.expire_all()
    reader = db_session.scalar(select(Reader).where(Reader.email == email))
    assert reader is not None
    assert reader.avatar_enqueued_at is not None
    request_reader_avatar(db_session, reader)
    db_session.commit()
    assert called["enqueue"] == 1
