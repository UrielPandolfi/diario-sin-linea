from __future__ import annotations

import hashlib
import logging
from uuid import UUID

from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.core.clock import utc_now
from app.core.db import SessionLocal
from app.domain.enums import ArticleStatus
from app.models import Article, ArticleHeroImage, ArticleVersion, Event
from app.services.hero_image_renderer import HEIGHT, WIDTH, TemplateHeroRenderer

logger = logging.getLogger(__name__)

TEMPLATE_VERSION = "template_v1"
_PENDING_KEY = "sl_hero_article_ids"
_HOOK_KEY = "sl_hero_after_commit"


def hero_fingerprint(headline: str, locality: str | None) -> str:
    raw = f"{TEMPLATE_VERSION}|{(headline or '').strip()}|{(locality or '').strip()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def hero_public_path(article_id: UUID, fingerprint: str) -> str:
    return f"/api/v1/media/heroes/{article_id}.png?v={fingerprint[:12]}"


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
        logger.exception("hero image ensure failed")
    finally:
        session.close()


class HeroImageService:
    def __init__(self, session: Session, renderer: TemplateHeroRenderer | None = None) -> None:
        self.session = session
        self.renderer = renderer or TemplateHeroRenderer()

    def persist(self, article_id: UUID) -> None:
        article = self.session.get(Article, article_id)
        if article is None:
            return
        if article.status != ArticleStatus.PUBLISHED or article.published_version is None:
            return
        event_row = self.session.get(Event, article.event_id)
        live = self.session.scalar(
            select(ArticleVersion).where(
                ArticleVersion.article_id == article.id,
                ArticleVersion.version_number == article.published_version,
            )
        )
        headline = live.headline if live is not None else article.headline
        locality = event_row.locality if event_row is not None else None
        fingerprint = hero_fingerprint(headline, locality)
        url = hero_public_path(article.id, fingerprint)
        existing = self.session.get(ArticleHeroImage, article.id)
        if existing is not None and existing.fingerprint == fingerprint and article.hero_image_url == url:
            return
        png = self.renderer.render(headline=headline, locality=locality)
        now = utc_now()
        if existing is None:
            self.session.add(
                ArticleHeroImage(
                    article_id=article.id,
                    png_bytes=png,
                    fingerprint=fingerprint,
                    content_type="image/png",
                    width=WIDTH,
                    height=HEIGHT,
                    updated_at=now,
                )
            )
        else:
            existing.png_bytes = png
            existing.fingerprint = fingerprint
            existing.content_type = "image/png"
            existing.width = WIDTH
            existing.height = HEIGHT
            existing.updated_at = now
        article.hero_image_url = url
        self.session.flush()
