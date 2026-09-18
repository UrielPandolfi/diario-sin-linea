from io import BytesIO
from uuid import uuid4

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.enums import ArticleStatus, EditorialRevisionKind, EventStatus
from app.main import app
from app.models import ArticleHeroImage, ArticleVersion
from app.services.editorial_service import EditorialService
from app.services.hero_image_renderer import (
    HEIGHT,
    MAX_HEADLINE_LINES,
    WIDTH,
    TemplateHeroRenderer,
    fit_headline,
    line_height,
)
from app.services.hero_image_service import (
    HeroImageService,
    ensure_in_own_session,
    hero_public_path,
)
from app.services.publish_service import PublishService
from tests.test_publishing import _audit_pass, _seed_draft


def _png(data: bytes) -> Image.Image:
    assert data.startswith(b"\x89PNG")
    return Image.open(BytesIO(data))


def _publish_and_commit(session: Session):
    event, article, _claim = _seed_draft(session)
    _audit_pass(session, event)
    result = PublishService(session).publish(event.id, trigger="test")
    session.commit()
    session.refresh(article)
    session.refresh(event)
    return event, article, result


def test_renderer_png_dimensions() -> None:
    png = TemplateHeroRenderer().render(headline="Choque en Pellegrini", locality="Rosario")
    image = _png(png)
    assert image.size == (WIDTH, HEIGHT)


def test_renderer_without_locality() -> None:
    png = TemplateHeroRenderer().render(headline="Anuncio oficial", locality=None)
    image = _png(png)
    assert image.size == (WIDTH, HEIGHT)


def test_long_headline_stays_within_line_cap() -> None:
    headline = "El municipio anunció un programa de obras " * 12
    lines, font = fit_headline(headline, max_width=1064, max_height=360)
    assert len(lines) <= MAX_HEADLINE_LINES
    assert line_height(font) * len(lines) <= 360
    png = TemplateHeroRenderer().render(headline=headline, locality="Villa Gobernador Gálvez")
    assert _png(png).size == (WIDTH, HEIGHT)


def test_unicode_headline_renders() -> None:
    png = TemplateHeroRenderer().render(
        headline="Ñandú en Córdoba — Pérez visitó San José",
        locality="San José de la Esquina",
    )
    assert _png(png).size == (WIDTH, HEIGHT)


def test_hero_public_path_is_relative() -> None:
    article_id = uuid4()
    url = hero_public_path(article_id, "abcdef1234567890")
    assert url == f"/api/v1/media/heroes/{article_id}.png?v=abcdef123456"
    assert not url.startswith("http")
    assert "api:8000" not in url


def test_ensure_is_idempotent(db_session: Session) -> None:
    _event, article, result = _publish_and_commit(db_session)
    assert result["published"] is True
    assert article.hero_image_url
    first_url = article.hero_image_url
    ensure_in_own_session(article.id)
    db_session.refresh(article)
    rows = db_session.scalar(select(func.count()).select_from(ArticleHeroImage))
    assert rows == 1
    assert article.hero_image_url == first_url


def test_fingerprint_skips_rerender_until_headline_changes(db_session: Session, monkeypatch) -> None:
    calls = {"n": 0}
    original = TemplateHeroRenderer.render

    def counting(self, **kwargs):
        calls["n"] += 1
        return original(self, **kwargs)

    monkeypatch.setattr(TemplateHeroRenderer, "render", counting)
    _event, article, _result = _publish_and_commit(db_session)
    assert calls["n"] == 1
    ensure_in_own_session(article.id)
    assert calls["n"] == 1
    article.headline = "Titular nuevo para la portada"
    version = db_session.scalar(
        select(ArticleVersion).where(
            ArticleVersion.article_id == article.id,
            ArticleVersion.version_number == article.published_version,
        )
    )
    assert version is not None
    version.headline = article.headline
    db_session.commit()
    ensure_in_own_session(article.id)
    db_session.refresh(article)
    assert calls["n"] == 2
    assert article.hero_image_url is not None
    assert "v=" in article.hero_image_url


def test_editorial_revise_new_headline_regenerates_hero(db_session: Session) -> None:
    event, article, _result = _publish_and_commit(db_session)
    first = article.hero_image_url
    assert first
    EditorialService(db_session).revise(
        event.id,
        base_published_version=article.published_version or 1,
        kind=EditorialRevisionKind.MINOR,
        headline="Otro titular con eñe en Córdoba",
        summary=article.summary,
        body=article.body,
    )
    db_session.commit()
    db_session.refresh(article)
    assert article.hero_image_url
    assert article.hero_image_url != first


def test_renderer_failure_does_not_revert_publish(db_session: Session, monkeypatch) -> None:
    def boom(self, **kwargs):
        raise RuntimeError("render failed")

    monkeypatch.setattr(TemplateHeroRenderer, "render", boom)
    event, article, result = _publish_and_commit(db_session)
    assert result["published"] is True
    assert result["reason"] == "published"
    assert article.status == ArticleStatus.PUBLISHED
    assert event.status == EventStatus.PUBLISHED
    assert article.hero_image_url is None
    assert db_session.get(ArticleHeroImage, article.id) is None


def test_persist_flush_failure_does_not_revert_publish(db_session: Session, monkeypatch) -> None:
    def boom(self, article_id):
        raise IntegrityError("INSERT", {}, Exception("hero flush"))

    monkeypatch.setattr(HeroImageService, "persist", boom)
    event, article, result = _publish_and_commit(db_session)
    assert result["published"] is True
    assert article.status == ArticleStatus.PUBLISHED
    assert event.status == EventStatus.PUBLISHED
    assert article.hero_image_url is None


def test_public_api_returns_hero_and_serves_png(db_session: Session) -> None:
    _event, article, _result = _publish_and_commit(db_session)
    assert article.hero_image_url
    with TestClient(app) as client:
        payload = client.get(f"/api/v1/articles/{article.slug}")
        image = client.get(article.hero_image_url)
    assert payload.status_code == 200
    assert payload.json()["hero_image_url"] == article.hero_image_url
    assert image.status_code == 200
    assert image.headers["content-type"].startswith("image/png")
    assert "max-age=31536000" in image.headers.get("cache-control", "")
    assert "immutable" in image.headers.get("cache-control", "")
    assert _png(image.content).size == (WIDTH, HEIGHT)


def test_public_article_allows_null_hero(db_session: Session, monkeypatch) -> None:
    def boom(self, article_id):
        raise IntegrityError("INSERT", {}, Exception("hero flush"))

    monkeypatch.setattr(HeroImageService, "persist", boom)
    _event, article, _result = _publish_and_commit(db_session)
    with TestClient(app) as client:
        payload = client.get(f"/api/v1/articles/{article.slug}")
    assert payload.status_code == 200
    assert payload.json()["hero_image_url"] is None


def test_feed_and_search_cards_include_hero_url(db_session: Session) -> None:
    _event, article, _result = _publish_and_commit(db_session)
    assert article.hero_image_url
    with TestClient(app) as client:
        feed = client.get("/api/v1/feed")
        live = client.get("/api/v1/live")
        search = client.get("/api/v1/search", params={"q": "Pellegrini"})
    feed_item = next(item for item in feed.json()["items"] if item["slug"] == article.slug)
    live_item = next(item for item in live.json()["items"] if item["slug"] == article.slug)
    search_item = next(item for item in search.json()["items"] if item["slug"] == article.slug)
    assert feed_item["hero_image_url"] == article.hero_image_url
    assert live_item["hero_image_url"] == article.hero_image_url
    assert search_item["hero_image_url"] == article.hero_image_url


def test_public_get_fills_missing_hero(db_session: Session) -> None:
    _event, article, _result = _publish_and_commit(db_session)
    row = db_session.get(ArticleHeroImage, article.id)
    assert row is not None
    db_session.delete(row)
    article.hero_image_url = None
    db_session.commit()
    with TestClient(app) as client:
        payload = client.get(f"/api/v1/articles/{article.slug}")
        feed = client.get("/api/v1/feed")
        assert payload.status_code == 200
        assert payload.json()["hero_image_url"]
        image = client.get(payload.json()["hero_image_url"])
    db_session.refresh(article)
    assert article.hero_image_url == payload.json()["hero_image_url"]
    feed_item = next(item for item in feed.json()["items"] if item["slug"] == article.slug)
    assert feed_item["hero_image_url"] == article.hero_image_url
    assert image.status_code == 200
    assert image.headers["content-type"].startswith("image/png")
