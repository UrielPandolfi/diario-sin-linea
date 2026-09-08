from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.core.article_body import ArticleDraftValidationError, merge_editorial_body_blocks
from app.core.clock import utc_now
from app.domain.enums import ArticleStatus, CorrectionKind, EditorialRevisionKind, EventStatus
from app.models import Correction
from app.repositories import ArticleRepository, EventRepository, PipelineRunRepository
from app.schemas import ArticleContentUpdate
from app.services.article_service import ArticleService
from app.services.pipeline_lock import is_write_audit_publish_busy

_KIND_REASON = {
    EditorialRevisionKind.MINOR: "editorial_minor",
    EditorialRevisionKind.UPDATE: "editorial_update",
    EditorialRevisionKind.CORRECTION: "editorial_correction",
}


class EditorialServiceError(ValueError):
    def __init__(self, code: str, http_status: int = 422) -> None:
        super().__init__(code)
        self.code = code
        self.http_status = http_status


class EditorialService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.articles = ArticleRepository(session)
        self.events = EventRepository(session)
        self.pipeline = PipelineRunRepository(session)
        self.article_service = ArticleService(session)

    def revise(
        self,
        event_id: UUID,
        *,
        base_published_version: int,
        kind: EditorialRevisionKind,
        headline: str,
        summary: str,
        body: str,
        public_notice: str | None = None,
        show_near_title: bool = False,
        reader_case_id: UUID | None = None,
    ) -> dict:
        event = self.events.get(event_id)
        if event is None:
            raise EditorialServiceError("event_not_found", 404)
        if is_write_audit_publish_busy(self.pipeline, event_id):
            raise EditorialServiceError("already_running", 409)

        article = self.articles.lock_by_event_id(event_id)
        if article is None:
            raise EditorialServiceError("article_not_found", 404)
        if article.published_version is None:
            raise EditorialServiceError("not_published", 409)
        if int(article.published_version) != int(base_published_version):
            raise EditorialServiceError("published_version_conflict", 409)

        live = self.articles.get_version(article.id, article.published_version)
        if live is None:
            raise EditorialServiceError("live_version_missing", 409)

        headline = (headline or "").strip()
        summary = (summary or "").strip()
        body_text = body or ""
        if not headline or not summary or not body_text.strip():
            raise EditorialServiceError("invalid_content")

        if kind in {EditorialRevisionKind.CORRECTION, EditorialRevisionKind.UPDATE}:
            notice = (public_notice or "").strip()
            if len(notice) < 20:
                raise EditorialServiceError("notice_required")
        else:
            notice = None

        try:
            merged_body, body_blocks = merge_editorial_body_blocks(live.body_blocks, body_text)
        except ArticleDraftValidationError as exc:
            raise EditorialServiceError("invalid_body") from exc

        article = self.article_service.update_content(
            article,
            ArticleContentUpdate(
                headline=headline,
                summary=summary,
                body=merged_body,
                body_blocks=body_blocks,
                change_reason=_KIND_REASON[kind],
            ),
        )
        now = utc_now()
        article.status = ArticleStatus.PUBLISHED
        article.published_version = article.current_version
        if article.published_at is None:
            article.published_at = now
        version = self.articles.get_version(article.id, article.current_version)
        if version is not None:
            version.published_at = now
        if event.status != EventStatus.ARCHIVED:
            event.status = EventStatus.PUBLISHED
        if event.slug is None:
            event.slug = article.slug

        correction = None
        if kind != EditorialRevisionKind.MINOR:
            new_version = self.articles.get_version(article.id, article.current_version)
            correction = Correction(
                article_id=article.id,
                article_version_id=new_version.id if new_version is not None else None,
                description=notice or "",
                reason=_KIND_REASON[kind],
                kind=CorrectionKind.CORRECTION if kind == EditorialRevisionKind.CORRECTION else CorrectionKind.UPDATE,
                show_near_title=bool(show_near_title) if kind == EditorialRevisionKind.CORRECTION else False,
                is_public=True,
                reader_case_id=reader_case_id,
            )
            self.session.add(correction)
            article.editorial_hold = True
            event.last_material_update_at = now
        self.session.flush()
        return {
            "published": True,
            "reason": "editorial_revised",
            "kind": kind.value,
            "version": article.current_version,
            "correction_id": str(correction.id) if correction is not None else None,
            "editorial_hold": article.editorial_hold,
        }
