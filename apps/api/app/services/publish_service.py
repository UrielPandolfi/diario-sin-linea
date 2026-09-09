from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.clock import utc_now
from app.domain.enums import ArticleStatus, EventStatus, EventUpdateType, PipelineStatus
from app.models import Article, Event, EventUpdate, PipelineRun
from app.repositories import ArticleRepository, EventRepository, PipelineRunRepository
from app.services.audit_policy import blocking_issues, structural_findings
from app.services.pipeline_lock import PUBLISHING_STAGE, is_write_audit_publish_busy

AUDITING_STAGE = "auditing"


class PublishService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.pipeline = PipelineRunRepository(session)
        self.articles = ArticleRepository(session)
        self.events = EventRepository(session)

    def publish(
        self,
        event_id: UUID,
        *,
        trigger: str,
        context: dict | None = None,
        override_editorial_hold: bool = False,
        target_version: int | None = None,
        base_published_version: int | None = None,
    ) -> dict:
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
            metadata_json={
                "trigger": trigger,
                "context": context or {},
                "override_editorial_hold": override_editorial_hold,
                "target_version": target_version,
                "base_published_version": base_published_version,
            },
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
            result = self._run(
                event,
                override_editorial_hold=override_editorial_hold,
                target_version=target_version,
                base_published_version=base_published_version,
            )
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
        if article.editorial_hold:
            return {"reason": "editorial_hold", "published": False}
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

    def _run(
        self,
        event: Event,
        *,
        override_editorial_hold: bool = False,
        target_version: int | None = None,
        base_published_version: int | None = None,
    ) -> dict:
        article = self.articles.lock_by_event_id(event.id)
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
        if article.editorial_hold:
            if not override_editorial_hold:
                base["reason"] = "editorial_hold"
                return base
            if target_version is None or int(target_version) != int(article.current_version):
                base["reason"] = "override_version_mismatch"
                return base
            if base_published_version is None or int(base_published_version) != int(
                article.published_version or -1
            ):
                base["reason"] = "published_version_conflict"
                return base
            base["editorial_hold_override"] = True
            base["from_published_version"] = article.published_version
            base["target_version"] = target_version
            base["override_at"] = utc_now().isoformat()
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
        version = self.articles.get_version(article.id, article.current_version)
        if version is not None:
            version.published_at = now
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
        run = self.pipeline.latest_completed(event_id, AUDITING_STAGE)
        if run is None or run.status != PipelineStatus.SUCCESS:
            return False
        meta = run.metadata_json or {}
        if meta.get("audited") is not True:
            return False
        passed = meta.get("passed")
        if passed is not True and passed != "true":
            return False
        version_after = meta.get("version_after")
        if version_after is None:
            return False
        if int(version_after) != int(article.current_version):
            return False
        snapshot = meta.get("evidence_snapshot")
        if not isinstance(snapshot, dict):
            return False
        bound = snapshot.get("version")
        if bound is None or int(bound) != int(article.current_version):
            return False
        if blocking_issues(structural_findings(snapshot, article)):
            return False
        return True
