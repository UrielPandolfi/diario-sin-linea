from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.domain.enums import ArticleStatus, EditorialRevisionKind, EventStatus
from app.main import app
from app.models import ArticleHeroImage
from app.providers.fakes import FakeStructuredLLM
from app.providers.base import ProviderNotConfiguredError
from app.providers.replicate_image import ReplicateImageProvider
from app.services.article_image_prompt_service import (
    ArticleImagePromptService,
    GeneratedImagePrompt,
)
from app.services.editorial_service import EditorialService
from app.services.hero_image_error import HeroImageError
from app.services.hero_image_service import (
    HeroImageService,
    ensure_in_own_session,
    hero_public_path,
)
from app.services.publish_service import PublishService
from tests.origin import ADMIN_ORIGIN
from tests.test_publishing import _audit_pass, _seed_draft

BODY_MARKER = "Hay heridos según el draft."


def _webp(color: tuple[int, int, int] = (30, 36, 40)) -> bytes:
    image = Image.new("RGB", (32, 18), color)
    buffer = BytesIO()
    image.save(buffer, format="WEBP", quality=80)
    return buffer.getvalue()


def _png() -> bytes:
    image = Image.new("RGB", (8, 8), (10, 10, 10))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class _Prompts:
    def __init__(self, prompt: str = "Muted editorial illustration of a courthouse", error: Exception | None = None) -> None:
        self.prompt = prompt
        self.error = error
        self.calls: list[tuple[str, str]] = []

    def generate(self, *, headline: str, summary: str) -> str:
        self.calls.append((headline, summary))
        if self.error is not None:
            raise self.error
        return self.prompt


class _Images:
    def __init__(self, payloads: list[bytes] | None = None, error: Exception | None = None) -> None:
        self.payloads = payloads or [_webp()]
        self.error = error
        self.calls: list[str] = []

    def generate(self, prompt: str) -> bytes:
        self.calls.append(prompt)
        if self.error is not None:
            raise self.error
        return self.payloads[min(len(self.calls) - 1, len(self.payloads) - 1)]


def _enable(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "article_image_enabled", True)
    monkeypatch.setattr(get_settings(), "article_image_model", "black-forest-labs/flux-schnell")
    monkeypatch.setattr(get_settings(), "article_image_output_format", "webp")
    monkeypatch.setattr(get_settings(), "image_prompt_provider", "deepseek")


def _install(monkeypatch, prompts: _Prompts, images: _Images) -> None:
    monkeypatch.setattr("app.services.hero_image_service.ArticleImagePromptService", lambda: prompts)
    monkeypatch.setattr("app.services.hero_image_service.ReplicateImageProvider", lambda: images)


def _publish(session: Session):
    event, article, _claim = _seed_draft(session)
    _audit_pass(session, event)
    result = PublishService(session).publish(event.id, trigger="test")
    session.commit()
    session.refresh(article)
    session.refresh(event)
    return event, article, result


def _login(client: TestClient) -> None:
    login = client.post("/api/v1/admin/login", json={"password": get_settings().admin_password})
    assert login.status_code == 200


def test_prompt_service_sends_only_headline_and_summary() -> None:
    llm = FakeStructuredLLM(
        {"GeneratedImagePrompt": GeneratedImagePrompt(prompt="Quiet institutional corridor")}
    )
    text = ArticleImagePromptService(llm=llm).generate(
        headline="Titular",
        summary="Bajada",
    )
    assert text == "Quiet institutional corridor"
    assert llm.user_prompts == ["Headline:\nTitular\n\nSummary:\nBajada"]
    assert BODY_MARKER not in llm.user_prompts[0]


def test_prompt_service_maps_provider_errors() -> None:
    missing = FakeStructuredLLM({"GeneratedImagePrompt": ProviderNotConfiguredError("no")})
    try:
        ArticleImagePromptService(llm=missing).generate(headline="Titular", summary="Bajada")
        raise AssertionError("debía fallar")
    except HeroImageError as exc:
        assert exc.code == "missing_image_prompt_config"


def test_replicate_provider_uses_settings_and_does_not_keep_token(monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "replicate_api_token", "token-de-prueba")
    monkeypatch.setattr(settings, "article_image_model", "black-forest-labs/flux-schnell")
    monkeypatch.setattr(settings, "article_image_go_fast", True)
    monkeypatch.setattr(settings, "article_image_megapixels", "1")
    monkeypatch.setattr(settings, "article_image_aspect_ratio", "16:9")
    monkeypatch.setattr(settings, "article_image_output_format", "webp")
    monkeypatch.setattr(settings, "article_image_output_quality", 80)
    monkeypatch.setattr(settings, "article_image_num_inference_steps", 4)
    captured: dict = {}

    def runner(model, input):
        captured["model"] = model
        captured["input"] = input
        captured["token"] = __import__("os").environ.get("REPLICATE_API_TOKEN")
        return [_webp()]

    data = ReplicateImageProvider(runner=runner).generate("a courthouse")
    assert data.startswith(b"RIFF")
    assert captured["model"] == "black-forest-labs/flux-schnell"
    assert captured["token"] == "token-de-prueba"
    assert captured["input"]["num_outputs"] == 1
    assert captured["input"]["prompt"] == "a courthouse"
    assert captured["input"]["output_format"] == "webp"
    assert __import__("os").environ.get("REPLICATE_API_TOKEN") != "token-de-prueba"


def test_replicate_provider_missing_token() -> None:
    settings = get_settings()
    previous = settings.replicate_api_token
    settings.replicate_api_token = None
    try:
        ReplicateImageProvider(runner=lambda *_a, **_k: b"x").generate("prompt")
        raise AssertionError("debía fallar")
    except HeroImageError as exc:
        assert exc.code == "missing_replicate_token"
        assert exc.http_status == 503
    finally:
        settings.replicate_api_token = previous


def test_hero_public_path_is_relative() -> None:
    from uuid import uuid4

    article_id = uuid4()
    url = hero_public_path(article_id, "abcdef1234567890")
    assert url == f"/api/v1/media/heroes/{article_id}.webp?v=abcdef123456"
    assert not url.startswith("http")


def test_publish_stores_webp_and_skips_body(db_session: Session, monkeypatch) -> None:
    _enable(monkeypatch)
    prompts = _Prompts()
    images = _Images()
    _install(monkeypatch, prompts, images)
    _event, article, result = _publish(db_session)
    assert result["published"] is True
    assert article.hero_image_url
    assert article.hero_image_url.startswith(f"/api/v1/media/heroes/{article.id}.webp?v=")
    assert prompts.calls == [("Un colectivo chocó en Pellegrini", "El choque ocurrió en Rosario.")]
    assert BODY_MARKER not in prompts.calls[0][0]
    assert BODY_MARKER not in prompts.calls[0][1]
    assert images.calls == ["Muted editorial illustration of a courthouse"]
    row = db_session.get(ArticleHeroImage, article.id)
    assert row is not None
    assert row.content_type == "image/webp"
    assert bytes(row.png_bytes).startswith(b"RIFF")
    with TestClient(app) as client:
        payload = client.get(f"/api/v1/articles/{article.slug}")
        image = client.get(article.hero_image_url)
    assert payload.json()["hero_image_url"] == article.hero_image_url
    assert image.status_code == 200
    assert image.headers["content-type"].startswith("image/webp")
    assert "immutable" in image.headers.get("cache-control", "")


def test_prompt_failure_does_not_publish_break_or_call_replicate(db_session: Session, monkeypatch) -> None:
    _enable(monkeypatch)
    prompts = _Prompts(error=HeroImageError("image_prompt_error", "falló", 502))
    images = _Images()
    _install(monkeypatch, prompts, images)
    event, article, result = _publish(db_session)
    assert result["published"] is True
    assert result["reason"] == "published"
    assert article.status == ArticleStatus.PUBLISHED
    assert event.status == EventStatus.PUBLISHED
    assert article.hero_image_url is None
    assert images.calls == []
    assert db_session.get(ArticleHeroImage, article.id) is None


def test_replicate_failure_leaves_article_without_hero(db_session: Session, monkeypatch) -> None:
    _enable(monkeypatch)
    prompts = _Prompts()
    images = _Images(error=HeroImageError("replicate_error", "falló", 502))
    _install(monkeypatch, prompts, images)
    event, article, result = _publish(db_session)
    assert result["published"] is True
    assert article.status == ArticleStatus.PUBLISHED
    assert event.status == EventStatus.PUBLISHED
    assert article.hero_image_url is None
    assert len(prompts.calls) == 1
    assert images.calls == ["Muted editorial illustration of a courthouse"]


def test_existing_hero_is_not_regenerated(db_session: Session, monkeypatch) -> None:
    _enable(monkeypatch)
    prompts = _Prompts()
    images = _Images()
    _install(monkeypatch, prompts, images)
    _event, article, _result = _publish(db_session)
    first = article.hero_image_url
    ensure_in_own_session(article.id)
    db_session.refresh(article)
    assert article.hero_image_url == first
    assert len(images.calls) == 1
    EditorialService(db_session).revise(
        _event.id,
        base_published_version=article.published_version or 1,
        kind=EditorialRevisionKind.MINOR,
        headline="Otro titular",
        summary=article.summary,
        body=article.body,
    )
    db_session.commit()
    db_session.refresh(article)
    assert article.hero_image_url == first
    assert len(images.calls) == 1


def test_force_replaces_hero(db_session: Session, monkeypatch) -> None:
    _enable(monkeypatch)
    prompts = _Prompts()
    images = _Images(payloads=[_webp((20, 20, 20)), _webp((80, 70, 60))])
    _install(monkeypatch, prompts, images)
    _event, article, _result = _publish(db_session)
    first = article.hero_image_url
    url = HeroImageService(db_session, prompts, images).generate_hero_for_article(article.id, force=True)
    db_session.commit()
    db_session.refresh(article)
    assert url != first
    assert article.hero_image_url == url
    assert len(images.calls) == 2
    row = db_session.get(ArticleHeroImage, article.id)
    assert row is not None
    assert bytes(row.png_bytes) == images.payloads[1]


def test_disabled_skips_automatic_generation(db_session: Session, monkeypatch) -> None:
    prompts = _Prompts()
    images = _Images()
    _install(monkeypatch, prompts, images)
    event, article, result = _publish(db_session)
    assert result["published"] is True
    assert event.status == EventStatus.PUBLISHED
    assert article.hero_image_url is None
    assert prompts.calls == []
    assert images.calls == []


def test_public_get_does_not_generate_missing_hero(db_session: Session, monkeypatch) -> None:
    _enable(monkeypatch)
    prompts = _Prompts()
    images = _Images()
    _install(monkeypatch, prompts, images)
    _event, article, _result = _publish(db_session)
    row = db_session.get(ArticleHeroImage, article.id)
    assert row is not None
    db_session.delete(row)
    article.hero_image_url = None
    db_session.commit()
    with TestClient(app) as client:
        payload = client.get(f"/api/v1/articles/{article.slug}")
    assert payload.status_code == 200
    assert payload.json()["hero_image_url"] is None
    assert len(images.calls) == 1


def test_legacy_png_route_still_serves_stored_bytes(db_session: Session) -> None:
    _event, article, _result = _publish(db_session)
    data = _png()
    db_session.add(
        ArticleHeroImage(
            article_id=article.id,
            png_bytes=data,
            fingerprint="abc123abc123abc123abc123abc123abc123abc123abc123abc123abc123abcd",
            content_type="image/png",
            width=8,
            height=8,
        )
    )
    article.hero_image_url = f"/api/v1/media/heroes/{article.id}.png?v=abc123abc123"
    db_session.commit()
    with TestClient(app) as client:
        image = client.get(article.hero_image_url)
    assert image.status_code == 200
    assert image.headers["content-type"].startswith("image/png")
    assert image.content.startswith(b"\x89PNG")


def test_admin_generate_hero_force_and_errors(db_session: Session, monkeypatch) -> None:
    prompts = _Prompts()
    images = _Images(payloads=[_webp((1, 2, 3)), _webp((4, 5, 6))])
    _install(monkeypatch, prompts, images)
    _event, article, _result = _publish(db_session)
    with TestClient(app) as client:
        denied = client.post(f"/api/v1/admin/articles/{article.id}/generate-hero", headers=ADMIN_ORIGIN)
        assert denied.status_code == 401
        _login(client)
        disabled = client.post(
            f"/api/v1/admin/articles/{article.id}/generate-hero",
            headers=ADMIN_ORIGIN,
        )
        assert disabled.status_code == 409
        _enable(monkeypatch)
        created = client.post(
            f"/api/v1/admin/articles/{article.id}/generate-hero",
            headers=ADMIN_ORIGIN,
        )
        assert created.status_code == 200
        first = created.json()["hero_image_url"]
        again = client.post(
            f"/api/v1/admin/articles/{article.id}/generate-hero",
            headers=ADMIN_ORIGIN,
        )
        assert again.status_code == 200
        assert again.json()["hero_image_url"] == first
        forced = client.post(
            f"/api/v1/admin/articles/{article.id}/generate-hero",
            headers=ADMIN_ORIGIN,
            params={"force": "true"},
        )
        assert forced.status_code == 200
        assert forced.json()["hero_image_url"] != first
    assert len(images.calls) == 2
    db_session.refresh(article)
    assert article.hero_image_url == forced.json()["hero_image_url"]
