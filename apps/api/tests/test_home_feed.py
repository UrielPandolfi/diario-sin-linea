"""Authenticated home: Principal ranking, Últimas, reads and likes."""

from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.clock import utc_now
from app.core.config import get_settings
from app.main import app
from app.models import ArticleVersion
from app.models.reader import Reader
from app.models.reader_signal import ReaderEventLike, ReaderEventRead
from app.services.reader_auth import issue_reader_token
from tests.reader_session import authenticate_reader
from tests.test_public_api import _publish_passed, _seed

NOW = utc_now()


def _ready(session: Session, *, locality: str, province: str, headline: str, hash_key: str, event_type: str, relevance: int, published_at: datetime, material_at: datetime | None = None):
    event, article = _seed(session, locality=locality, headline=headline, hash_key=hash_key)
    _publish_passed(session, event)
    session.refresh(event)
    session.refresh(article)
    event.locality = locality
    event.province = province
    event.country_code = "AR"
    event.event_type = event_type
    event.relevance_score = relevance
    event.last_material_update_at = material_at
    article.published_at = published_at
    article.updated_at = published_at
    event.updated_at = published_at
    session.commit()
    return event, article


def _slugs(client: TestClient, **params: str) -> list[str]:
    response = client.get("/api/v1/feed", params=params)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    payload = response.json()
    assert "email" not in payload
    for item in payload["items"]:
        assert "score" not in item
    return [item["slug"] for item in payload["items"]]


def test_home_sorts_reject_anonymous_and_unknown_values(db_session: Session) -> None:
    event, article = _ready(
        db_session,
        locality="Rosario",
        province="Santa Fe",
        headline="Nota que no debe listarse",
        hash_key="home-anon",
        event_type="accidente",
        relevance=80,
        published_at=NOW,
    )
    with TestClient(app) as client:
        for sort in ("principal", "latest"):
            denied = client.get("/api/v1/feed", params={"sort": sort})
            assert denied.status_code == 401
            assert "Nota que no debe listarse" not in denied.text
        authenticate_reader(client, email="home-sort@sinlinea.test")
        assert client.get("/api/v1/feed", params={"sort": "viral"}).status_code == 400
        reader = db_session.scalar(select(Reader).where(Reader.email == "home-sort@sinlinea.test"))
        assert reader is not None
        expired = issue_reader_token(reader.id, get_settings().app_secret, now=1, ttl=10)
        client.cookies.set("sl_reader", expired)
        expired_feed = client.get("/api/v1/feed", params={"sort": "principal"})
        assert expired_feed.status_code == 401
        assert article.slug not in expired_feed.text
        assert client.put(f"/api/v1/articles/{article.slug}/like").status_code == 401
        assert client.post(f"/api/v1/articles/{article.slug}/read").status_code == 401
    assert db_session.scalar(select(func.count()).select_from(ReaderEventLike)) == 0
    assert db_session.scalar(select(func.count()).select_from(ReaderEventRead)) == 0
    del event


def test_principal_base_rank_locality_and_latest_publication(db_session: Session) -> None:
    national, national_article = _ready(
        db_session,
        locality="Buenos Aires",
        province="Buenos Aires",
        headline="Nacional",
        hash_key="home-nac",
        event_type="economia",
        relevance=100,
        published_at=NOW,
    )
    local, local_article = _ready(
        db_session,
        locality="Rosario",
        province="Santa Fe",
        headline="Local",
        hash_key="home-local",
        event_type="accidente",
        relevance=90,
        published_at=NOW,
    )
    city, city_article = _ready(
        db_session,
        locality="Córdoba",
        province="Córdoba",
        headline="Ciudad",
        hash_key="home-city",
        event_type="economia",
        relevance=50,
        published_at=NOW,
    )
    same_province, same_province_article = _ready(
        db_session,
        locality="Villa María",
        province="Córdoba",
        headline="Provincia",
        hash_key="home-prov",
        event_type="economia",
        relevance=50,
        published_at=NOW - timedelta(hours=1),
    )
    homonym_a, homonym_a_article = _ready(
        db_session,
        locality="San Justo",
        province="Santa Fe",
        headline="San Justo Santa Fe",
        hash_key="home-sj-sf",
        event_type="economia",
        relevance=40,
        published_at=NOW,
    )
    homonym_b, homonym_b_article = _ready(
        db_session,
        locality="San Justo",
        province="Buenos Aires",
        headline="San Justo Buenos Aires",
        hash_key="home-sj-ba",
        event_type="economia",
        relevance=40,
        published_at=NOW,
    )
    anchor, anchor_article = _ready(
        db_session,
        locality="La Plata",
        province="Buenos Aires",
        headline="Ancla",
        hash_key="home-anchor",
        event_type="economia",
        relevance=70,
        published_at=NOW,
    )
    aged, aged_article = _ready(
        db_session,
        locality="Rosario",
        province="Santa Fe",
        headline="Vieja relevante",
        hash_key="home-old",
        event_type="economia",
        relevance=100,
        published_at=NOW - timedelta(hours=72),
    )
    fresh_low, fresh_article = _ready(
        db_session,
        locality="Rosario",
        province="Santa Fe",
        headline="Nueva baja",
        hash_key="home-new",
        event_type="economia",
        relevance=0,
        published_at=NOW,
    )
    material, material_article = _ready(
        db_session,
        locality="Mendoza",
        province="Mendoza",
        headline="Actualizada",
        hash_key="home-mat",
        event_type="economia",
        relevance=10,
        published_at=NOW - timedelta(hours=48),
        material_at=NOW,
    )
    quiet, quiet_article = _ready(
        db_session,
        locality="Mendoza",
        province="Mendoza",
        headline="Sin retoque",
        hash_key="home-quiet",
        event_type="economia",
        relevance=10,
        published_at=NOW - timedelta(hours=24),
    )
    del national, local, city, same_province, homonym_a, homonym_b, anchor, aged, fresh_low, material, quiet

    with TestClient(app) as first, TestClient(app) as second:
        authenticate_reader(first, email="sin-historial-a@sinlinea.test")
        authenticate_reader(second, email="sin-historial-b@sinlinea.test")
        without = _slugs(first, sort="principal")
        assert without == _slugs(second, sort="principal")
        assert without.index(national_article.slug) < without.index(local_article.slug)

        rosario = _slugs(first, sort="principal", locality="Rosario")
        assert rosario.index(local_article.slug) < rosario.index(national_article.slug)
        villa = _slugs(first, sort="principal", locality="Villa María")
        assert villa.index(same_province_article.slug) < villa.index(city_article.slug)
        ambiguous = _slugs(first, sort="principal", locality="San Justo")
        assert ambiguous.index(anchor_article.slug) < ambiguous.index(homonym_a_article.slug)
        assert ambiguous.index(anchor_article.slug) < ambiguous.index(homonym_b_article.slug)
        assert _slugs(first, sort="principal", locality="Rosario").index(fresh_article.slug) > _slugs(
            first, sort="principal", locality="Rosario"
        ).index(aged_article.slug)

        latest_a = _slugs(first, sort="latest")
        latest_b = _slugs(second, sort="latest")
        assert latest_a == latest_b
        assert latest_a.index(quiet_article.slug) < latest_a.index(material_article.slug)
        principal_mendoza = _slugs(first, sort="principal", locality="Mendoza")
        assert principal_mendoza.index(material_article.slug) < principal_mendoza.index(quiet_article.slug)

        material_article.updated_at = utc_now()
        db_session.commit()
        assert _slugs(first, sort="latest").index(quiet_article.slug) < _slugs(first, sort="latest").index(
            material_article.slug
        )


def test_affinity_reads_and_likes_are_bounded_and_private(db_session: Session) -> None:
    economy, economy_article = _ready(
        db_session,
        locality="Rosario",
        province="Santa Fe",
        headline="Economía",
        hash_key="aff-eco",
        event_type="economia",
        relevance=100,
        published_at=NOW,
    )
    accident, accident_article = _ready(
        db_session,
        locality="Rosario",
        province="Santa Fe",
        headline="Accidente",
        hash_key="aff-acc",
        event_type="accidente",
        relevance=80,
        published_at=NOW,
    )
    extras = []
    for index in range(5):
        event, article = _ready(
            db_session,
            locality="Rosario",
            province="Santa Fe",
            headline=f"Señal {index}",
            hash_key=f"aff-sig-{index}",
            event_type="accidente",
            relevance=1,
            published_at=NOW - timedelta(days=index + 1),
        )
        extras.append((event, article))
    draft_event, draft = _seed(db_session, locality="Rosario", headline="Borrador afinidad", hash_key="aff-draft")
    db_session.commit()
    db_session.add(
        ArticleVersion(
            article_id=economy_article.id,
            version_number=2,
            headline="Candidata secreta de economía",
            summary="no publicar",
            body="no publicar",
        )
    )
    economy_article.current_version = 2
    db_session.commit()

    with TestClient(app) as reader, TestClient(app) as other, TestClient(app) as anon:
        authenticate_reader(reader, email="afinidad@sinlinea.test")
        authenticate_reader(other, email="otra-afinidad@sinlinea.test")
        base = _slugs(reader, sort="principal", locality="Rosario")
        assert base.index(economy_article.slug) < base.index(accident_article.slug)
        assert "Candidata secreta de economía" not in reader.get("/api/v1/feed", params={"sort": "principal"}).text
        assert draft.slug not in base

        one = reader.post(f"/api/v1/articles/{extras[0][1].slug}/read")
        assert one.status_code == 204
        assert reader.post(f"/api/v1/articles/{extras[0][1].slug}/read").status_code == 204
        db_session.expire_all()
        assert db_session.scalar(select(func.count()).select_from(ReaderEventRead)) == 1
        after_one = _slugs(reader, sort="principal", locality="Rosario")
        assert after_one.index(economy_article.slug) < after_one.index(accident_article.slug)

        for _event, article in extras:
            liked = reader.put(f"/api/v1/articles/{article.slug}/like")
            assert liked.status_code == 200
            assert liked.json() == {"liked": True}
            assert liked.headers["cache-control"] == "private, no-store"
        again = reader.put(f"/api/v1/articles/{extras[0][1].slug}/like")
        assert again.status_code == 200
        db_session.expire_all()
        assert db_session.scalar(select(func.count()).select_from(ReaderEventLike)) == 5
        boosted = _slugs(reader, sort="principal", locality="Rosario")
        assert boosted.index(accident_article.slug) < boosted.index(economy_article.slug)
        assert _slugs(other, sort="principal", locality="Rosario").index(economy_article.slug) < _slugs(
            other, sort="principal", locality="Rosario"
        ).index(accident_article.slug)
        assert _slugs(reader, sort="latest") == _slugs(other, sort="latest")

        assert other.get(f"/api/v1/articles/{extras[0][1].slug}/like").json() == {"liked": False}
        assert other.delete(f"/api/v1/articles/{extras[0][1].slug}/like").status_code == 200
        assert reader.get(f"/api/v1/articles/{extras[0][1].slug}/like").json() == {"liked": True}
        for _event, article in extras:
            assert reader.delete(f"/api/v1/articles/{article.slug}/like").json() == {"liked": False}
        restored = _slugs(reader, sort="principal", locality="Rosario")
        assert restored.index(economy_article.slug) < restored.index(accident_article.slug)

        assert anon.post(f"/api/v1/articles/{accident_article.slug}/read").status_code == 401
        assert anon.put(f"/api/v1/articles/{accident_article.slug}/like").status_code == 401
        assert anon.put(f"/api/v1/articles/{draft.slug}/like").status_code == 401
        assert reader.put(f"/api/v1/articles/{draft.slug}/like").status_code == 404
    del economy, accident, draft_event


def test_principal_pages_cover_the_ranked_set_once(db_session: Session) -> None:
    articles = []
    for relevance, name in ((100, "alta"), (50, "media"), (0, "baja")):
        _event, article = _ready(
            db_session,
            locality="Paraná",
            province="Entre Ríos",
            headline=name,
            hash_key=f"page-{name}",
            event_type="economia",
            relevance=relevance,
            published_at=NOW,
        )
        articles.append(article)
    with TestClient(app) as client:
        authenticate_reader(client, email="paginas@sinlinea.test")
        seen: list[str] = []
        cursor = None
        for _ in range(3):
            params = {"sort": "principal", "locality": "Paraná", "limit": "1"}
            if cursor:
                params["cursor"] = cursor
            response = client.get("/api/v1/feed", params=params)
            assert response.status_code == 200
            page = response.json()
            assert len(page["items"]) == 1
            seen.append(page["items"][0]["slug"])
            cursor = page["next_cursor"]
        assert cursor is None
        assert seen == [articles[0].slug, articles[1].slug, articles[2].slug]
        assert len(seen) == len(set(seen))
