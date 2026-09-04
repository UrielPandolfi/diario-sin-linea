from datetime import datetime
from typing import NamedTuple

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.source_content import has_extracted_body, is_extracted_body
from app.core.text import content_fingerprint, postgres_safe_text
from app.domain.enums import SourceItemStatus
from app.models import SourceItem
from app.repositories import SourceItemRepository
from app.schemas import SourceItemCreate


class IngestOutcome(NamedTuple):
    item: SourceItem
    created: bool
    updated: bool


def _is_blank(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return False


class SourceItemService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repo = SourceItemRepository(session)

    def ingest(self, data: SourceItemCreate) -> IngestOutcome:
        data = data.model_copy(
            update={
                "title": postgres_safe_text(data.title),
                "raw_text": postgres_safe_text(data.raw_text),
                "clean_text": postgres_safe_text(data.clean_text),
                "excerpt": postgres_safe_text(data.excerpt),
                "author": postgres_safe_text(data.author),
            }
        )
        existing = self._find_publication(data)
        if existing is not None:
            updated = self._refresh_content(existing, data)
            return IngestOutcome(existing, False, updated)

        item = SourceItem(**data.model_dump())
        self.repo.add(item)
        try:
            with self.session.begin_nested():
                self.session.flush()
        except IntegrityError:
            existing = self._find_publication(data)
            if existing is None:
                raise
            updated = self._refresh_content(existing, data)
            return IngestOutcome(existing, False, updated)
        return IngestOutcome(item, True, False)

    def enrich_content(
        self,
        item: SourceItem,
        *,
        url: str | None = None,
        canonical_url: str | None = None,
        title: str | None = None,
        raw_text: str | None = None,
        clean_text: str | None = None,
        excerpt: str | None = None,
        author: str | None = None,
        published_at: datetime | None = None,
    ) -> bool:
        title = postgres_safe_text(title)
        raw_text = postgres_safe_text(raw_text)
        clean_text = postgres_safe_text(clean_text)
        excerpt = postgres_safe_text(excerpt)
        author = postgres_safe_text(author)
        changed = False
        if not _is_blank(url) and url != item.url:
            item.url = url
            changed = True
        if not _is_blank(canonical_url) and not item.canonical_url:
            item.canonical_url = canonical_url
            changed = True
        if _is_blank(item.title) and not _is_blank(title):
            item.title = title
            changed = True
        if _is_blank(item.author) and not _is_blank(author):
            item.author = author
            changed = True
        if item.published_at is None and published_at is not None:
            item.published_at = published_at
            changed = True

        incoming_ok = is_extracted_body(clean_text, title or item.title)
        existing_ok = has_extracted_body(item)
        if incoming_ok:
            incoming = (clean_text or "").strip()
            current = (item.clean_text or "").strip()
            if not existing_ok or len(incoming) > len(current):
                item.clean_text = incoming
                changed = True
                if not _is_blank(excerpt):
                    item.excerpt = excerpt.strip()[:500]
                elif not item.excerpt:
                    item.excerpt = incoming[:500]

        if not _is_blank(raw_text):
            incoming_raw = raw_text.strip()
            current_raw = (item.raw_text or "").strip()
            if not current_raw or len(incoming_raw) > len(current_raw):
                item.raw_text = incoming_raw
                changed = True

        if (
            not _is_blank(excerpt)
            and _is_blank(item.excerpt)
            and is_extracted_body(excerpt, title or item.title)
        ):
            item.excerpt = excerpt.strip()[:500]
            changed = True

        if changed:
            item.content_hash = content_fingerprint(title=item.title, body=item.clean_text)
        return changed

    def _find_publication(self, data: SourceItemCreate) -> SourceItem | None:
        if data.external_id:
            existing = self.repo.get_by_source_and_external_id(data.source_id, data.external_id)
            if existing is not None:
                return existing
        if data.canonical_url:
            return self.repo.get_by_source_and_canonical_url(data.source_id, data.canonical_url)
        return None

    def _refresh_content(self, item: SourceItem, data: SourceItemCreate) -> bool:
        if item.content_hash == data.content_hash:
            return False
        item.content_hash = data.content_hash
        item.url = data.url
        item.canonical_url = data.canonical_url or item.canonical_url
        item.external_id = data.external_id or item.external_id
        item.title = postgres_safe_text(data.title)
        item.raw_text = postgres_safe_text(data.raw_text)
        item.clean_text = postgres_safe_text(data.clean_text)
        item.excerpt = postgres_safe_text(data.excerpt)
        item.author = postgres_safe_text(data.author)
        item.published_at = data.published_at
        item.processing_status = SourceItemStatus.PENDING
        return True
