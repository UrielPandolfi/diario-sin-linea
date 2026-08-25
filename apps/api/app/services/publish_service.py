from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.clock import utc_now
from app.domain.enums import ArticleStatus, EventStatus, EventUpdateType, PipelineStatus
from app.models import Article, Event, EventUpdate, PipelineRun
from app.repositories import ArticleRepository, EventRepository, PipelineRunRepository
from app.services.pipeline_lock import PUBLISHING_STAGE, is_write_audit_publish_busy

AUDITING_STAGE = "auditing"


class PublishService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.pipeline = PipelineRunRepository(session)
        self.articles = ArticleRepository(session)
        self.events = EventRepository(session)

    def publish(self, event_id: UUID, *, trigger: str, context: dict | None = None) -> dict:
        event = self.events.get(event_id)
        if event is None:
            raise ValueError("event_not_found")
        original_status = event.status

        if is_write_audit_publish_busy(self.pipeline, event_id):
            return {
                "skipped": True,
                "reason": "already_running",
                "event_id": str(event_id),
                "published": False,
            }

        run = PipelineRun(
            event_id=event.id,
            stage=PUBLISHING_STAGE,
            status=PipelineStatus.RUNNING,
            metadata_json={"trigger": trigger, "context": context or {}},
        )
        try:
            with self.session.begin_nested():
                self.pipeline.add(run)
                self.session.flush()
        except IntegrityError:
            if run in self.session:
                self.session.expunge(run)
            return {
                "skipped": True,
                "reason": "already_running",
                "event_id": str(event_id),
                "published": False,
            }

        try:
            result = self._run(event)
            run.status = PipelineStatus.SUCCESS
            run.finished_at = utc_now()
            run.metadata_json = {**(run.metadata_json or {}), **result}
            if not result.get("published"):
                event.status = original_status
            self.session.flush()
            return {"skipped": False, "event_id": str(event.id), **result}
        except Exception as exc:
            return self._fail(run, event, original_status, str(exc))

    def inspect_publish(self, event_id: UUID) -> dict:
        event = self.events.get(event_id)
        if event is None:
            raise ValueError("event_not_found")
        article = self.articles.get_by_event_id(event.id)
        if article is None:
            return {"reason": "no_article", "published": False}
        if article.status == ArticleStatus.ARCHIVED or event.status == EventStatus.ARCHIVED:
            return {"reason": "archived", "published": False}
        if (
            article.status == ArticleStatus.PUBLISHED
            and article.published_version is not None
            and article.published_version == article.current_version
        ):
            return {"reason": "already_published", "published": True}
        if not self._audit_passed_for_current(event.id, article):
            return {"reason": "audit_not_passed", "published": False}
        return {"reason": "ready", "published": False}

    def archive(self, event_id: UUID) -> dict:
        event = self.events.get(event_id)
        if event is None:
            raise ValueError("event_not_found")
        if is_write_audit_publish_busy(self.pipeline, event_id):
            return {"skipped": True, "reason": "already_running", "event_id": str(event_id)}
        article = self.articles.get_by_event_id(event.id)
        if article is not None:
            if article.status == ArticleStatus.ARCHIVED and event.status == EventStatus.ARCHIVED:
                return {
                    "skipped": False,
                    "reason": "already_archived",
                    "event_id": str(event.id),
                    "archived": True,
                }
            article.status = ArticleStatus.ARCHIVED
        event.status = EventStatus.ARCHIVED
        self.session.flush()
        return {"skipped": False, "reason": "archived", "event_id": str(event.id), "archived": True}

    def _fail(self, run: PipelineRun, event: Event, original_status: Any, message: str) -> dict:
        run.status = PipelineStatus.FAILED
        run.error_message = message
        run.finished_at = utc_now()
        event.status = original_status
        self.session.flush()
        return {
            "skipped": False,
            "event_id": str(event.id),
            "published": False,
            "error": message,
        }

    def _run(self, event: Event) -> dict:
        article = self.articles.get_by_event_id(event.id)
        base: dict[str, Any] = {
            "article_id": str(article.id) if article is not None else None,
            "published": False,
            "reason": None,
            "version": article.current_version if article is not None else None,
        }
        if article is None:
            base["reason"] = "no_article"
            return base
        if article.status == ArticleStatus.ARCHIVED or event.status == EventStatus.ARCHIVED:
            base["reason"] = "archived"
            return base
        if (
            article.status == ArticleStatus.PUBLISHED
            and article.published_version is not None
            and article.published_version == article.current_version
        ):
            base["published"] = True
            base["reason"] = "already_published"
            return base
        if not self._audit_passed_for_current(event.id, article):
            base["reason"] = "audit_not_passed"
            return base

        now = utc_now()
        first_publish = article.published_at is None or article.published_version is None
        if article.published_at is None:
            article.published_at = now
        article.published_version = article.current_version
        article.status = ArticleStatus.PUBLISHED
        event.status = EventStatus.PUBLISHED
        if event.slug is None:
            event.slug = article.slug
        if not first_publish:
            event.last_material_update_at = now
        self.session.add(
            EventUpdate(
                event_id=event.id,
                update_type=EventUpdateType.ARTICLE_UPDATED,
                headline=article.headline,
                summary=article.summary,
                is_material=True,
                occurred_at=now,
            )
        )
        base.update(
            {
                "published": True,
                "reason": "published",
                "version": article.current_version,
                "first_publish": first_publish,
            }
        )
        return base

    def _audit_passed_for_current(self, event_id: UUID, article: Article) -> bool:
        run = self.pipeline.latest_success(event_id, AUDITING_STAGE)
        if run is None:
            return False
        meta = run.metadata_json or {}
        passed = meta.get("passed")
        if passed is not True and passed != "true":
            return False
        version_after = meta.get("version_after")
        if version_after is None:
            return False
        return int(version_after) == int(article.current_version)
