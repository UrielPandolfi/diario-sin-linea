"""Private saved articles: session, uniqueness, isolation and the published version."""

from datetime import timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.clock import utc_now
from app.domain.enums import EventStatus
from app.main import app
from app.models import ArticleVersion
from app.models.reader_signal import ReaderEventLike, ReaderEventSave
from tests.reader_session import authenticate_reader
from tests.test_home_feed import NOW, _ready
from tests.test_public_api import _seed

INTERNAL = "Titular interno no publicar"


def _saves(session: Session) -> list[ReaderEventSave]:
    session.expire_all()
    return list(session.scalars(select(ReaderEventSave)))


def test_saved_requires_session_and_stays_private(db_session: Session) -> None:
    _event, article = _ready(
        db_session,
        locality="Rosario",
        province="Santa Fe",
        headline="Nota guardable",
        hash_key="save-public",
        event_type="accidente",
        relevance=40,
        published_at=NOW,
    )
    _draft_event, draft = _seed(db_session, locality="Rosario", headline="Borrador secreto", hash_key="save-draft")
    db_session.commit()

    with TestClient(app) as client:
        for method, path in (
            ("GET", "/api/v1/saved"),
            ("GET", f"/api/v1/articles/{article.slug}/save"),
            ("PUT", f"/api/v1/articles/{article.slug}/save"),
            ("DELETE", f"/api/v1/articles/{article.slug}/save"),
            ("PUT", f"/api/v1/articles/{draft.slug}/save"),
        ):
            denied = client.request(method, path)
            assert denied.status_code == 401
            assert "Nota guardable" not in denied.text
            assert "Borrador secreto" not in denied.text

        authenticate_reader(client, email="guardar-a@sinlinea.test")
        missing = client.put(f"/api/v1/articles/{draft.slug}/save")
        assert missing.status_code == 404
        assert "Borrador secreto" not in missing.text

        saved = client.put(f"/api/v1/articles/{article.slug}/save")
        assert saved.status_code == 200
        assert saved.json() == {"saved": True}
        assert saved.headers["cache-control"] == "private, no-store"
        again = client.put(f"/api/v1/articles/{article.slug}/save")
        assert again.json() == {"saved": True}
        state = client.get(f"/api/v1/articles/{article.slug}/save")
        assert state.json() == {"saved": True}

        listed = client.get("/api/v1/saved")
        assert listed.status_code == 200
        assert listed.headers["cache-control"] == "private, no-store"
        assert [item["slug"] for item in listed.json()["items"]] == [article.slug]
        assert "saved" not in listed.json()["items"][0]
        public = client.get(f"/api/v1/articles/{article.slug}")
        assert "saved" not in public.json()
        assert "saved_count" not in public.json()

        removed = client.delete(f"/api/v1/articles/{article.slug}/save")
        assert removed.json() == {"saved": False}
        again_removed = client.delete(f"/api/v1/articles/{article.slug}/save")
        assert again_removed.json() == {"saved": False}
        assert client.get("/api/v1/saved").json()["items"] == []

    assert _saves(db_session) == []
    assert db_session.scalar(select(func.count()).select_from(ReaderEventLike)) == 0


def test_saved_order_isolation_and_published_version(db_session: Session) -> None:
    older_event, older = _ready(
        db_session,
        locality="Rosario",
        province="Santa Fe",
        headline="Guardada primero",
        hash_key="save-old",
        event_type="accidente",
        relevance=20,
        published_at=NOW - timedelta(days=2),
    )
    newer_event, newer = _ready(
        db_session,
        locality="Córdoba",
        province="Córdoba",
        headline="Guardada después",
        hash_key="save-new",
        event_type="economia",
        relevance=80,
        published_at=NOW,
    )
    published = db_session.scalar(
        select(ArticleVersion).where(
            ArticleVersion.article_id == newer.id,
            ArticleVersion.version_number == newer.published_version,
        )
    )
    assert published is not None
    db_session.add(
        ArticleVersion(
            id=uuid4(),
            article_id=newer.id,
            version_number=int(newer.published_version) + 1,
            headline=INTERNAL,
            summary="Resumen interno",
            body=published.body,
        )
    )
    db_session.commit()

    with TestClient(app) as owner:
        authenticate_reader(owner, email="guardar-a@sinlinea.test")
        assert owner.put(f"/api/v1/articles/{older.slug}/save").status_code == 200
        assert owner.put(f"/api/v1/articles/{newer.slug}/save").status_code == 200

    moment = utc_now()
    for row in _saves(db_session):
        row.saved_at = moment - timedelta(hours=1) if row.event_id == older_event.id else moment - timedelta(days=2)
    db_session.commit()
    first_saved_at = {row.event_id: row.saved_at for row in _saves(db_session)}

    with TestClient(app) as owner:
        authenticate_reader(owner, email="guardar-a@sinlinea.test")
        assert owner.put(f"/api/v1/articles/{newer.slug}/save").status_code == 200
        page = owner.get("/api/v1/saved", params={"limit": 1})
        assert page.status_code == 200
        assert [item["headline"] for item in page.json()["items"]] == ["Guardada primero"]
        assert INTERNAL not in page.text
        cursor = page.json()["next_cursor"]
        assert cursor
        rest = owner.get("/api/v1/saved", params={"limit": 1, "cursor": cursor})
        assert [item["headline"] for item in rest.json()["items"]] == ["Guardada después"]
        assert rest.json()["next_cursor"] is None
        seen = {page.json()["items"][0]["slug"], rest.json()["items"][0]["slug"]}
        assert seen == {older.slug, newer.slug}
        assert owner.get("/api/v1/saved", params={"cursor": "no-es-uuid"}).status_code == 400

    assert {row.event_id: row.saved_at for row in _saves(db_session)} == first_saved_at

    with TestClient(app) as other:
        authenticate_reader(other, email="guardar-b@sinlinea.test")
        assert other.get("/api/v1/saved").json()["items"] == []
        assert other.delete(f"/api/v1/articles/{newer.slug}/save").json() == {"saved": False}
        assert other.get(f"/api/v1/articles/{newer.slug}/save").json() == {"saved": False}

    assert len(_saves(db_session)) == 2

    newer_event.status = EventStatus.ARCHIVED
    db_session.commit()
    with TestClient(app) as owner:
        authenticate_reader(owner, email="guardar-a@sinlinea.test")
        hidden = owner.get("/api/v1/saved")
        assert hidden.status_code == 200
        assert [item["slug"] for item in hidden.json()["items"]] == [older.slug]
        assert INTERNAL not in hidden.text
        assert "Guardada después" not in hidden.text
        blocked = owner.get(f"/api/v1/articles/{newer.slug}/save")
        assert blocked.status_code == 404
        assert INTERNAL not in blocked.text
