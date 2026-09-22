from __future__ import annotations

import hashlib
import logging
from io import BytesIO
from uuid import UUID, uuid4

from PIL import Image
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.core.clock import utc_now
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.usage_context import usage_scope
from app.domain.enums import ArticleStatus
from app.models import Article, ArticleHeroImage, ArticleVersion
from app.providers.registry import ModelRole
from app.providers.replicate_image import ReplicateImageProvider
from app.services.article_image_prompt_service import ArticleImagePromptService
from app.services.hero_image_error import HeroImageError

logger = logging.getLogger(__name__)

_PENDING_KEY = "sl_hero_article_ids"
_HOOK_KEY = "sl_hero_after_commit"
_CONTENT_TYPES = {
    "webp": "image/webp",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
}


def hero_public_path(article_id: UUID, fingerprint: str, *, extension: str = "webp") -> str:
    ext = (extension or "webp").lower().lstrip(".")
    if ext == "jpeg":
        ext = "jpg"
    return f"/api/v1/media/heroes/{article_id}.{ext}?v={fingerprint[:12]}"


def schedule_after_commit(session: Session, article_id: UUID) -> None:
    pending: set[UUID] = session.info.setdefault(_PENDING_KEY, set())
    pending.add(article_id)
    if session.info.get(_HOOK_KEY):
        return
    session.info[_HOOK_KEY] = True

    def _run(sess: Session) -> None:
        ids = list(sess.info.pop(_PENDING_KEY, set()))
        sess.info.pop(_HOOK_KEY, None)
        for item_id in ids:
            ensure_in_own_session(item_id)

    event.listen(session, "after_commit", _run, once=True)


def ensure_in_own_session(article_id: UUID) -> None:
    session = SessionLocal()
    try:
        HeroImageService(session).persist(article_id)
        session.commit()
    except Exception:
        session.rollback()
        logger.exception("article_id=%s stage=hero_image provider=replicate status=error", article_id)
    finally:
        session.close()


def fill_missing_hero(session: Session, article: Article) -> None:
    """La lectura pública no llama a Replicate. La portada se intenta al publicar."""
    del session, article


def _editorial_copy(session: Session, article: Article) -> tuple[str, str]:
    number = article.published_version if article.published_version is not None else article.current_version
    version = session.scalar(
        select(ArticleVersion).where(
            ArticleVersion.article_id == article.id,
            ArticleVersion.version_number == number,
        )
    )
    if version is not None:
        return (version.headline or "").strip(), (version.summary or "").strip()
    return (article.headline or "").strip(), (article.summary or "").strip()


def _image_size(data: bytes) -> tuple[int, int]:
    try:
        with Image.open(BytesIO(data)) as image:
            return int(image.width), int(image.height)
    except Exception:
        return 1200, 630


class HeroImageService:
    def __init__(
        self,
        session: Session,
        prompt_service: ArticleImagePromptService | None = None,
        image_provider: ReplicateImageProvider | None = None,
    ) -> None:
        self.session = session
        self.prompts = prompt_service or ArticleImagePromptService()
        self.images = image_provider or ReplicateImageProvider()

    def persist(self, article_id: UUID) -> None:
        if not get_settings().article_image_enabled:
            return
        article = self.session.get(Article, article_id)
        if article is None:
            return
        if article.status != ArticleStatus.PUBLISHED or article.published_version is None:
            return
        if article.hero_image_url:
            return
        try:
            self.generate_hero_for_article(article_id, force=False)
        except HeroImageError:
            self.session.rollback()
        except Exception:
            self.session.rollback()
            logger.exception(
                "article_id=%s stage=hero_image provider=replicate status=error",
                article_id,
            )

    def generate_hero_for_article(self, article_id: UUID, *, force: bool = False) -> str:
        settings = get_settings()
        if not settings.article_image_enabled:
            raise HeroImageError(
                "disabled",
                "La generación de imágenes está desactivada",
                409,
            )
        article = self.session.get(Article, article_id)
        if article is None:
            raise HeroImageError("not_found", "Artículo no encontrado", 404)
        if article.hero_image_url and not force:
            return article.hero_image_url
        provider_name = (settings.image_prompt_provider or "").strip().lower() or "unconfigured"
        headline, summary = _editorial_copy(self.session, article)
        if not headline or not summary:
            logger.warning(
                "article_id=%s stage=image_prompt provider=%s status=error",
                article.id,
                provider_name,
            )
            raise HeroImageError(
                "missing_text",
                "El artículo no tiene titular o bajada",
                422,
            )
        try:
            with usage_scope(
                stage="image_prompt",
                event_id=article.event_id,
                model_role=ModelRole.IMAGE_PROMPT.value,
                provider=None if provider_name == "unconfigured" else provider_name,
            ):
                prompt = self.prompts.generate(headline=headline, summary=summary)
        except HeroImageError:
            logger.warning(
                "article_id=%s stage=image_prompt provider=%s status=error",
                article.id,
                provider_name,
            )
            raise
        logger.info(
            "article_id=%s stage=image_prompt provider=%s status=success",
            article.id,
            provider_name,
        )
        model = settings.article_image_model
        try:
            image = self.images.generate(prompt)
            url = self._store(article, image, extension=settings.article_image_output_format)
        except HeroImageError:
            logger.warning(
                "article_id=%s stage=hero_image provider=replicate model=%s status=error",
                article.id,
                model,
            )
            raise
        except Exception as exc:
            logger.warning(
                "article_id=%s stage=hero_image provider=replicate model=%s status=error",
                article.id,
                model,
            )
            raise HeroImageError("storage_error", "No se pudo guardar la imagen", 500) from exc
        logger.info(
            "article_id=%s stage=hero_image provider=replicate model=%s status=success",
            article.id,
            model,
        )
        return url

    def _store(self, article: Article, data: bytes, *, extension: str) -> str:
        if not data:
            raise HeroImageError("empty_output", "El modelo no devolvió una imagen", 502)
        fmt = (extension or "webp").lower().lstrip(".")
        content_type = _CONTENT_TYPES.get(fmt, "image/webp")
        width, height = _image_size(data)
        fingerprint = hashlib.sha256(f"{article.id}|{uuid4()}".encode()).hexdigest()
        url = hero_public_path(article.id, fingerprint, extension=fmt)
        now = utc_now()
        existing = self.session.get(ArticleHeroImage, article.id)
        try:
            if existing is None:
                self.session.add(
                    ArticleHeroImage(
                        article_id=article.id,
                        png_bytes=data,
                        fingerprint=fingerprint,
                        content_type=content_type,
                        width=width,
                        height=height,
                        updated_at=now,
                    )
                )
            else:
                existing.png_bytes = data
                existing.fingerprint = fingerprint
                existing.content_type = content_type
                existing.width = width
                existing.height = height
                existing.updated_at = now
            article.hero_image_url = url
            self.session.flush()
        except HeroImageError:
            raise
        except Exception as exc:
            self.session.rollback()
            raise HeroImageError("storage_error", "No se pudo guardar la imagen", 500) from exc
        return url
