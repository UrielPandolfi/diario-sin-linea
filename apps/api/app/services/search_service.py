from __future__ import annotations

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, aliased, selectinload

from app.models import Article, ArticleVersion, Entity, Event, EventEntity, EventSource, SourceItem
from app.services.feed_ranking import (
    PUBLIC_CANDIDATE_CAP,
    card_payload,
    clamp_limit,
    normalize_locality,
    public_filters,
)


class SearchService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def search(self, *, query: str, locality: str | None = None, limit: int = 20) -> dict:
        q = (query or "").strip()
        if not q:
            raise ValueError("query_required")
        live = aliased(ArticleVersion)
        tsquery = func.websearch_to_tsquery("spanish", q)
        like = f"%{q}%"
        stmt = (
            select(Event, Article, live)
            .join(Article, Article.event_id == Event.id)
            .join(
                live,
                and_(live.article_id == Article.id, live.version_number == Article.published_version),
            )
            .options(
                selectinload(Event.event_sources)
                .selectinload(EventSource.source_item)
                .selectinload(SourceItem.source)
            )
            .where(*public_filters())
            .where(
                or_(
                    live.search_tsv.op("@@")(tsquery),
                    Event.locality.ilike(like),
                    Event.id.in_(
                        select(EventEntity.event_id)
                        .join(Entity, Entity.id == EventEntity.entity_id)
                        .where(Entity.name.ilike(like))
                    ),
                )
            )
            .order_by(Article.published_at.desc())
            .limit(min(clamp_limit(limit), PUBLIC_CANDIDATE_CAP))
        )
        wanted = normalize_locality(locality)
        items = []
        for event, article, live_row in self.session.execute(stmt):
            if wanted and normalize_locality(event.locality) != wanted:
                continue
            items.append(card_payload(event, article, live_row))
        return {"items": items, "query": q}
