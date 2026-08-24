from typing import NamedTuple

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.enums import SourceItemStatus
from app.models import SourceItem
from app.repositories import SourceItemRepository
from app.schemas import SourceItemCreate


class IngestOutcome(NamedTuple):
    item: SourceItem
    created: bool
    updated: bool


class SourceItemService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repo = SourceItemRepository(session)

    def ingest(self, data: SourceItemCreate) -> IngestOutcome:
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
        item.title = data.title
        item.raw_text = data.raw_text
        item.clean_text = data.clean_text
        item.excerpt = data.excerpt
        item.author = data.author
        item.published_at = data.published_at
        item.processing_status = SourceItemStatus.PENDING
        return True
