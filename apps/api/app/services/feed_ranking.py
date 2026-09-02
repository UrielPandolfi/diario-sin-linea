from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import Select, and_, select
from sqlalchemy.orm import Session, aliased, selectinload

from app.core.clock import utc_now
from app.core.config import get_settings
from app.domain.enums import ArticleStatus, EventStatus, EventUpdateType, PipelineStatus
from app.models import (
    Article,
    ArticleVersion,
    Claim,
    Event,
    EventSource,
    EventUpdate,
    PipelineRun,
    SourceItem,
)
from app.repositories import ArticleRepository, EventRepository

PUBLIC_CANDIDATE_CAP = 200
DEFAULT_LIMIT = 20
MAX_LIMIT = 50


def clamp_limit(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_LIMIT
    return max(1, min(limit, MAX_LIMIT))


def normalize_locality(value: str | None) -> str:
    return (value or "").casefold().strip()


def locality_matches(event_locality: str | None, wanted: str) -> bool:
    return bool(wanted) and normalize_locality(event_locality) == normalize_locality(wanted)


def public_filters():
    return (
        Article.published_at.is_not(None),
        Article.published_version.is_not(None),
        Article.status != ArticleStatus.ARCHIVED,
        Event.status != EventStatus.ARCHIVED,
    )


def public_sort_at(event: Event, article: Article) -> datetime:
    return event.last_material_update_at or article.published_at or utc_now()


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def live_content(session: Session, article: Article) -> ArticleVersion | None:
    if article.published_version is None:
        return None
    return ArticleRepository(session).get_version(article.id, article.published_version)


def source_payloads(event: Event) -> list[dict]:
    rows: list[dict] = []
    seen: set[str] = set()
    for link in event.event_sources:
        item = link.source_item
        if item is None:
            continue
        source = item.source
        url = item.canonical_url or item.url
        key = url or str(item.id)
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "name": source.name if source is not None else None,
                "domain": source.domain if source is not None else None,
                "url": url,
                "title": item.title,
            }
        )
    return rows


def card_payload(event: Event, article: Article, live: ArticleVersion, *, score: float | None = None) -> dict:
    payload = {
        "slug": article.slug,
        "public_id": str(event.public_id),
        "headline": live.headline,
        "summary": live.summary,
        "locality": event.locality,
        "province": event.province,
        "published_at": iso(article.published_at),
        "updated_at": iso(event.last_material_update_at),
        "sources": source_payloads(event),
    }
    if score is not None:
        payload["score"] = score
    return payload


def compact_public_claims(session: Session, event: Event) -> list[dict]:
    sol_by_id: dict[str, dict] = {}
    run = session.scalars(
        select(PipelineRun)
        .where(
            PipelineRun.event_id == event.id,
            PipelineRun.stage == "verification",
            PipelineRun.status == PipelineStatus.SUCCESS,
        )
        .order_by(PipelineRun.finished_at.desc())
    ).first()
    if run is not None:
        for row in (run.metadata_json or {}).get("sol") or []:
            if not isinstance(row, dict) or not row.get("claim_id"):
                continue
            sol_by_id[str(row["claim_id"])] = {
                "status_after": row.get("status_after"),
                "unresolved": row.get("unresolved"),
                "reason": row.get("reason"),
            }
    rows: list[dict] = []
    for claim in event.claims:
        source_ids = {str(item.source_item_id) for item in claim.evidence if item.source_item_id}
        rows.append(
            {
                "id": str(claim.id),
                "canonical_text": claim.canonical_text,
                "status": claim.status.value,
                "importance": claim.importance.value,
                "source_count": len(source_ids),
                "evidence_count": len(claim.evidence),
                "verification": sol_by_id.get(str(claim.id)),
            }
        )
    return rows


def article_payload(event: Event, article: Article, live: ArticleVersion, *, session: Session) -> dict:
    return {
        **card_payload(event, article, live),
        "body": live.body,
        "body_blocks": live.body_blocks,
        "hero_image_url": article.hero_image_url,
        "claims": compact_public_claims(session, event),
    }


class FeedRankingService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.settings = get_settings()
        self.articles = ArticleRepository(session)
        self.events = EventRepository(session)

    def feed(self, *, scope: str, locality: str | None, limit: int, cursor: str | None) -> dict:
        scope = (scope or "main").casefold().strip()
        if scope not in {"main", "local", "argentina"}:
            raise ValueError("invalid_scope")
        wanted = normalize_locality(locality)
        if scope == "local" and not wanted:
            raise ValueError("locality_required")
        rows = self._load_public()
        if scope == "local":
            rows = [(event, article, live) for event, article, live in rows if locality_matches(event.locality, wanted)]
        ranked = [self._rank_row(event, article, live, scope=scope, locality=wanted) for event, article, live in rows]
        ranked.sort(
            key=lambda row: (
                -row[0],
                -(row[1].published_at or utc_now()).timestamp(),
                str(row[1].id),
            )
        )
        items, next_cursor = self._paginate_scored(ranked, limit=limit, cursor=cursor)
        return {"items": items, "next_cursor": next_cursor}

    def live(self, *, limit: int, cursor: str | None) -> dict:
        rows = self._load_public()
        rows.sort(key=lambda row: (public_sort_at(row[0], row[1]), str(row[1].id)), reverse=True)
        items, next_cursor = self._paginate_time(rows, limit=limit, cursor=cursor)
        return {"items": items, "next_cursor": next_cursor}

    def now(self, *, limit: int) -> dict:
        live = aliased(ArticleVersion)
        stmt = (
            select(EventUpdate, Event, Article)
            .join(Event, Event.id == EventUpdate.event_id)
            .join(Article, Article.event_id == Event.id)
            .join(
                live,
                and_(live.article_id == Article.id, live.version_number == Article.published_version),
            )
            .where(*public_filters())
            .where(EventUpdate.update_type == EventUpdateType.ARTICLE_UPDATED)
            .where(EventUpdate.is_material.is_(True))
            .order_by(EventUpdate.occurred_at.desc())
            .limit(clamp_limit(limit))
        )
        items = []
        for update, event, article in self.session.execute(stmt):
            items.append(
                {
                    "occurred_at": iso(update.occurred_at),
                    "locality": event.locality,
                    "headline": update.headline,
                    "slug": article.slug,
                    "public_id": str(event.public_id),
                }
            )
        return {"items": items}

    def nearby(self, *, locality: str, limit: int) -> dict:
        wanted = normalize_locality(locality)
        if not wanted:
            raise ValueError("locality_required")
        cutoff = utc_now() - timedelta(hours=self.settings.nearby_window_hours)
        rows = [
            (event, article, live)
            for event, article, live in self._load_public()
            if locality_matches(event.locality, wanted) and public_sort_at(event, article) >= cutoff
        ]
        rows.sort(key=lambda row: (public_sort_at(row[0], row[1]), str(row[1].id)), reverse=True)
        items = [card_payload(event, article, live) for event, article, live in rows[: clamp_limit(limit)]]
        return {"items": items}

    def localities(self) -> dict:
        names: list[str] = []
        seen: set[str] = set()
        for event, _article, _live in self._load_public():
            label = (event.locality or "").strip()
            key = normalize_locality(label)
            if not key or key in seen:
                continue
            seen.add(key)
            names.append(label)
        names.sort(key=lambda value: value.casefold())
        return {"items": names}

    def get_article(self, key: str) -> dict | None:
        article = None
        event = None
        try:
            public_id = UUID(key)
            event = self.events.get_by_public_id(public_id)
            if event is not None:
                article = self.articles.get_by_event_id(event.id)
        except ValueError:
            article = self.articles.get_by_slug(key)
            if article is not None:
                event = self.events.get(article.event_id)
        if article is None or event is None:
            return None
        if not self._is_public(event, article):
            return None
        live = live_content(self.session, article)
        if live is None:
            return None
        event = self._event_with_sources(event.id) or event
        return article_payload(event, article, live, session=self.session)

    def _is_public(self, event: Event, article: Article) -> bool:
        if article.published_at is None or article.published_version is None:
            return False
        if article.status == ArticleStatus.ARCHIVED:
            return False
        return event.status != EventStatus.ARCHIVED

    def _event_with_sources(self, event_id: UUID) -> Event | None:
        stmt = (
            select(Event)
            .options(
                selectinload(Event.event_sources)
                .selectinload(EventSource.source_item)
                .selectinload(SourceItem.source),
                selectinload(Event.claims).selectinload(Claim.evidence),
            )
            .where(Event.id == event_id)
        )
        return self.session.scalars(stmt).first()

    def _load_public(self) -> list[tuple[Event, Article, ArticleVersion]]:
        live = aliased(ArticleVersion)
        stmt: Select = (
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
            .order_by(Article.published_at.desc())
            .limit(PUBLIC_CANDIDATE_CAP)
        )
        return [(event, article, live_row) for event, article, live_row in self.session.execute(stmt)]

    def _rank_row(
        self,
        event: Event,
        article: Article,
        live: ArticleVersion,
        *,
        scope: str,
        locality: str,
    ) -> tuple[float, Article, Event, ArticleVersion]:
        settings = self.settings
        age = utc_now() - public_sort_at(event, article)
        age_hours = max(0.0, age.total_seconds() / 3600)
        freshness = 1.0 / (1.0 + age_hours / 6.0)
        relevance = (event.relevance_score or 0) / 100.0
        boost = 0.0
        if scope == "main" and locality and locality_matches(event.locality, locality):
            boost = 1.0
        score = (
            settings.feed_relevance_weight * relevance
            + settings.feed_freshness_weight * freshness
            + settings.feed_locality_weight * boost
        )
        return (score, article, event, live)

    def _paginate_scored(
        self,
        ranked: list[tuple[float, Article, Event, ArticleVersion]],
        *,
        limit: int,
        cursor: str | None,
    ) -> tuple[list[dict], str | None]:
        start = 0
        if cursor:
            cursor_id = _decode_id_cursor(cursor)
            start = next((index + 1 for index, row in enumerate(ranked) if row[1].id == cursor_id), len(ranked))
        window = ranked[start : start + limit]
        items = [card_payload(event, article, live, score=round(score, 6)) for score, article, event, live in window]
        next_cursor = str(window[-1][1].id) if len(window) == limit and start + limit < len(ranked) else None
        return items, next_cursor

    def _paginate_time(
        self,
        rows: list[tuple[Event, Article, ArticleVersion]],
        *,
        limit: int,
        cursor: str | None,
    ) -> tuple[list[dict], str | None]:
        start = 0
        if cursor:
            cursor_id = _decode_id_cursor(cursor)
            start = next((index + 1 for index, row in enumerate(rows) if row[1].id == cursor_id), len(rows))
        window = rows[start : start + limit]
        items = [card_payload(event, article, live) for event, article, live in window]
        next_cursor = str(window[-1][1].id) if len(window) == limit and start + limit < len(rows) else None
        return items, next_cursor


def _decode_id_cursor(cursor: str) -> UUID:
    try:
        return UUID(cursor)
    except ValueError as exc:
        raise ValueError("invalid_cursor") from exc
