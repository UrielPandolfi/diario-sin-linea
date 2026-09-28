from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID

from sqlalchemy import Select, and_, select
from sqlalchemy.orm import Session, aliased, selectinload

from app.core.article_body import claim_ids_in_body_blocks
from app.core.clock import utc_now
from app.core.config import Settings, get_settings
from app.domain.enums import ArticleStatus, ClaimImportance, ClaimStatus, CorrectionKind, EventStatus, EventUpdateType, EvidenceType
from app.models import (
    Article,
    ArticleVersion,
    Claim,
    ClaimEvidence,
    Correction,
    Event,
    EventSource,
    EventUpdate,
    SourceItem,
)
from app.models.reader_signal import ReaderEventSave
from app.repositories import ArticleRepository, EventRepository, PipelineRunRepository
from app.schemas.editorial_evidence import decision_was_evaluated
from app.services.claim_card_presentation import (
    presentation_for_claim,
    public_presentation_payload,
    public_verification_payload,
)
from app.services.editorial_gate import event_geo_keys, geo_places_conflict, item_geo_keys
from app.services.editorial_label_policy import editorial_public_payload, labels_for_event_claims
from app.services.editorial_reason import public_resolution_fields
from app.services.public_rendering import public_rendering_payload
from app.services.evidence_snapshot import (
    evidence_snapshot_for_version,
    snapshot_context_claims,
    snapshot_evaluated_texts,
    snapshot_sources_by_ref,
)
from app.services.feed_score import (
    PrincipalWeights,
    base_score,
    build_profile,
    empty_profile,
    freshness_unit,
    principal_reference,
    principal_score,
    proximity,
    relevance_unit,
    resolve_place,
)
from app.services.hero_image_service import fill_missing_hero
from app.services.reader_engagement import signal_ids
from app.services.verification_outcome import verification_view_for_event, view_from_evidence_snapshot

PUBLIC_CANDIDATE_CAP = 200
DEFAULT_LIMIT = 20
MAX_LIMIT = 50
SITEMAP_CAP = 10_000


class _VersionClaim:
    """Claim proxy bound to a version snapshot. Does not read live evidence/status."""

    def __init__(
        self,
        *,
        claim_id: str,
        live: Claim | None,
        row: dict | None,
        decision: dict | None,
        sources_by_ref: dict[int, dict],
        evaluated_text: str | None,
    ) -> None:
        self.id = live.id if live is not None else UUID(str(claim_id))
        row = row or {}
        decision = decision if isinstance(decision, dict) else {}
        # Status and proposition come from the version snapshot only. Live Claim
        # rows may already reflect a later Verification and must not fill gaps.
        status_raw = decision.get("status") or row.get("status")
        self.status = _parse_claim_status(status_raw, ClaimStatus.SINGLE_SOURCE)
        text = row.get("canonical_text") or evaluated_text
        self.canonical_text = str(text) if text else ""
        self.claim_type = row.get("claim_type")
        self.importance = _parse_importance(row.get("importance"), ClaimImportance.MEDIUM)
        self.subject = row.get("subject")
        self.predicate = row.get("predicate")
        self.object_text = row.get("object_text")
        self.normalized_value = row.get("normalized_value")
        self.unit = row.get("unit")
        self.occurred_at = _parse_dt(row.get("occurred_at")) if "occurred_at" in row else None
        self.evidence = _evidence_from_snapshot(row.get("evidence") or [], sources_by_ref)

    def __getattr__(self, name: str):
        raise AttributeError(name)


def _parse_claim_status(raw: object, fallback: ClaimStatus) -> ClaimStatus:
    if isinstance(raw, ClaimStatus):
        return raw
    if raw is None:
        return fallback
    try:
        return ClaimStatus(str(raw))
    except ValueError:
        return fallback


def _parse_importance(raw: object, fallback: ClaimImportance) -> ClaimImportance:
    if isinstance(raw, ClaimImportance):
        return raw
    if raw is None:
        return fallback
    try:
        return ClaimImportance(str(raw))
    except ValueError:
        return fallback


def _parse_dt(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _parse_evidence_type(raw: object) -> EvidenceType:
    if isinstance(raw, EvidenceType):
        return raw
    try:
        return EvidenceType(str(raw))
    except ValueError:
        return EvidenceType.MENTIONS


def _evidence_from_snapshot(rows: list, sources_by_ref: dict[int, dict]) -> list:
    evidence: list = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            ref = int(row.get("source_ref"))
        except (TypeError, ValueError):
            continue
        source = sources_by_ref.get(ref) or {}
        url = source.get("url")
        name = source.get("name") or source.get("title")
        key = str(url or ref)
        if key in seen:
            continue
        seen.add(key)
        evidence.append(
            SimpleNamespace(
                evidence_type=_parse_evidence_type(row.get("evidence_type")),
                excerpt=row.get("excerpt"),
                source_item_id=f"snapshot:{ref}",
                source_url=url,
                source_item=SimpleNamespace(
                    url=url,
                    canonical_url=url,
                    title=source.get("title") or name,
                    source=SimpleNamespace(
                        name=name,
                        domain=source.get("domain"),
                        source_type=None,
                    ),
                ),
            )
        )
    return evidence


def _frozen_public_claims(
    session: Session,
    event: Event,
    *,
    version: int,
    allowed_ids: set[str] | None,
) -> tuple[list, object]:
    runs = PipelineRunRepository(session).list_snapshot_binding_runs(event.id, version)
    snapshot = evidence_snapshot_for_version(runs, version)
    view = view_from_evidence_snapshot(snapshot)
    rows_meta = snapshot_context_claims(snapshot)
    texts = snapshot_evaluated_texts(snapshot)
    sources_by_ref = snapshot_sources_by_ref(snapshot)
    decisions = view.decision_by_claim_id
    snapshot_ids = set(rows_meta) | set(decisions) | set(texts)
    if allowed_ids is not None:
        membership = snapshot_ids & allowed_ids if snapshot_ids else set(allowed_ids)
    else:
        membership = snapshot_ids
    live_by_id = {str(claim.id): claim for claim in event.claims}
    ordered: list[str] = []
    seen: set[str] = set()
    for claim in event.claims:
        cid = str(claim.id)
        if cid in membership and cid not in seen:
            ordered.append(cid)
            seen.add(cid)
    for cid in membership:
        if cid not in seen:
            ordered.append(cid)
            seen.add(cid)
    frozen = []
    for cid in ordered:
        frozen.append(
            _VersionClaim(
                claim_id=cid,
                live=live_by_id.get(cid),
                row=rows_meta.get(cid),
                decision=decisions.get(cid) if isinstance(decisions.get(cid), dict) else None,
                sources_by_ref=sources_by_ref,
                evaluated_text=texts.get(cid),
            )
        )
    return frozen, view


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
    event_places = event_geo_keys(event)
    for link in event.event_sources:
        item = link.source_item
        if item is None:
            continue
        if geo_places_conflict(event_places, item_geo_keys(item)):
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


def card_payload(
    event: Event,
    article: Article,
    live: ArticleVersion,
    *,
    score: float | None = None,
    session: Session | None = None,
) -> dict:
    if session is not None:
        fill_missing_hero(session, article)
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
        "hero_image_url": article.hero_image_url,
    }
    if score is not None:
        payload["score"] = score
    return payload


def compact_public_claims(
    session: Session, event: Event, *, allowed_ids: set[str] | None = None, freeze_to_version: int | None = None
) -> list[dict]:
    if freeze_to_version is not None:
        claims, view = _frozen_public_claims(
            session, event, version=freeze_to_version, allowed_ids=allowed_ids
        )
    else:
        claims = list(event.claims)
        if allowed_ids is not None:
            claims = [claim for claim in claims if str(claim.id) in allowed_ids]
        _run, view = verification_view_for_event(session, event.id)
    editorials = labels_for_event_claims(list(claims), view)
    rows: list[dict] = []
    for claim in claims:
        cid = str(claim.id)
        if allowed_ids is not None and cid not in allowed_ids:
            continue
        source_ids = {str(item.source_item_id) for item in claim.evidence if getattr(item, "source_item_id", None)}
        card = presentation_for_claim(claim, view)
        decision = view.decision_by_claim_id.get(cid)
        payload = {
            "id": cid,
            "canonical_text": claim.canonical_text,
            "status": claim.status.value,
            "importance": claim.importance.value,
            "source_count": len(source_ids),
            "evidence_count": len(source_ids),
            "presentation": public_presentation_payload(card),
            "verification": public_verification_payload(view.sol_by_id.get(cid)),
        }
        payload.update(editorial_public_payload(editorials.get(cid)))
        if isinstance(decision, dict) and decision_was_evaluated(decision):
            payload.update(public_resolution_fields(decision))
        else:
            payload.update(public_resolution_fields(None))
        payload["public_rendering"] = public_rendering_payload(decision if isinstance(decision, dict) else None)
        rows.append(payload)
    return rows


def public_notices(corrections: list[Correction]) -> list[dict]:
    return [
        {
            "kind": row.kind.value,
            "notice": row.description,
            "occurred_at": iso(row.created_at),
            "show_near_title": row.show_near_title,
        }
        for row in corrections
    ]


def public_history(
    article: Article,
    corrections: list[Correction],
    updates: list[EventUpdate],
) -> list[dict]:
    items: list[dict] = []
    if article.published_at is not None:
        items.append(
            {
                "type": "published",
                "occurred_at": iso(article.published_at),
                "notice": None,
                "headline": None,
            }
        )
    for row in corrections:
        items.append(
            {
                "type": "correction" if row.kind == CorrectionKind.CORRECTION else "update",
                "occurred_at": iso(row.created_at),
                "notice": row.description,
                "headline": None,
            }
        )
    published_at = article.published_at
    for update in updates:
        if update.update_type != EventUpdateType.ARTICLE_UPDATED or not update.is_material:
            continue
        if published_at is not None and update.occurred_at <= published_at + timedelta(seconds=2):
            continue
        items.append(
            {
                "type": "pipeline_update",
                "occurred_at": iso(update.occurred_at),
                "notice": None,
                "headline": update.headline,
            }
        )
    items.sort(key=lambda row: row["occurred_at"] or "")
    return items


def article_payload(event: Event, article: Article, live: ArticleVersion, *, session: Session) -> dict:
    allowed = claim_ids_in_body_blocks(live.body_blocks)
    corrections = ArticleRepository(session).list_public_corrections(article.id)
    updates = list(
        session.scalars(
            select(EventUpdate)
            .where(EventUpdate.event_id == event.id)
            .order_by(EventUpdate.occurred_at.asc())
        ).all()
    )
    return {
        **card_payload(event, article, live, session=session),
        "body": live.body,
        "body_blocks": live.body_blocks,
        "hero_image_url": article.hero_image_url,
        "published_version": article.published_version,
        "article_id": str(article.id),
        "notices": public_notices(corrections),
        "history": public_history(article, corrections, updates),
        "claims": compact_public_claims(
            session, event, allowed_ids=allowed, freeze_to_version=article.published_version
        ),
    }


class FeedRankingService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.settings = get_settings()
        self.articles = ArticleRepository(session)
        self.events = EventRepository(session)

    def feed(
        self,
        *,
        scope: str,
        locality: str | None,
        limit: int,
        cursor: str | None,
        sort: str | None = None,
        reader_id: UUID | None = None,
    ) -> dict:
        if sort is not None and str(sort).strip():
            return self._sorted_feed(
                sort=str(sort),
                locality=locality,
                limit=limit,
                cursor=cursor,
                reader_id=reader_id,
            )
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

    def saved(self, *, reader_id: UUID, limit: int, cursor: str | None) -> dict:
        live = aliased(ArticleVersion)
        stmt: Select = (
            select(Event, Article, live)
            .join(Article, Article.event_id == Event.id)
            .join(
                live,
                and_(live.article_id == Article.id, live.version_number == Article.published_version),
            )
            .join(ReaderEventSave, ReaderEventSave.event_id == Event.id)
            .options(
                selectinload(Event.event_sources)
                .selectinload(EventSource.source_item)
                .selectinload(SourceItem.source)
            )
            .where(ReaderEventSave.reader_id == reader_id)
            .where(*public_filters())
            .order_by(ReaderEventSave.saved_at.desc(), Article.id.asc())
        )
        rows = [(event, article, live_row) for event, article, live_row in self.session.execute(stmt)]
        start = 0
        if cursor:
            cursor_id = _decode_id_cursor(cursor)
            found = next((index + 1 for index, row in enumerate(rows) if row[1].id == cursor_id), None)
            if found is None:
                raise ValueError("invalid_cursor")
            start = found
        window = rows[start : start + limit]
        items = [card_payload(event, article, live, session=self.session) for event, article, live in window]
        next_cursor = str(window[-1][1].id) if len(window) == limit and start + limit < len(rows) else None
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
                    "kind": "pipeline_update",
                }
            )
        corr_stmt = (
            select(Correction, Event, Article)
            .join(Article, Article.id == Correction.article_id)
            .join(Event, Event.id == Article.event_id)
            .where(*public_filters())
            .where(Correction.is_public.is_(True))
            .order_by(Correction.created_at.desc())
            .limit(clamp_limit(limit))
        )
        for correction, event, article in self.session.execute(corr_stmt):
            items.append(
                {
                    "occurred_at": iso(correction.created_at),
                    "locality": event.locality,
                    "headline": article.headline,
                    "slug": article.slug,
                    "public_id": str(event.public_id),
                    "kind": correction.kind.value.lower(),
                }
            )
        items.sort(key=lambda row: (row["occurred_at"] or "", row["slug"]), reverse=True)
        return {"items": items[: clamp_limit(limit)]}

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
        items = [
            card_payload(event, article, live, session=self.session)
            for event, article, live in rows[: clamp_limit(limit)]
        ]
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

    def sitemap_articles(self) -> dict:
        live = aliased(ArticleVersion)
        stmt = (
            select(Article.slug, Article.published_at, Event.last_material_update_at)
            .join(Event, Event.id == Article.event_id)
            .join(
                live,
                and_(live.article_id == Article.id, live.version_number == Article.published_version),
            )
            .where(*public_filters())
            .order_by(Article.published_at.desc())
            .limit(SITEMAP_CAP)
        )
        items = []
        for slug, published_at, updated_at in self.session.execute(stmt):
            items.append(
                {
                    "slug": slug,
                    "published_at": iso(published_at),
                    "updated_at": iso(updated_at),
                }
            )
        return {"items": items}

    def get_article(self, key: str) -> dict | None:
        article, event = self._lookup(key)
        if article is None or event is None or not self._is_public(event, article):
            return None
        live = live_content(self.session, article)
        if live is None:
            return None
        event = self._event_with_sources(event.id) or event
        return article_payload(event, article, live, session=self.session)

    def public_event_id(self, key: str) -> UUID | None:
        article, event = self._lookup(key)
        if article is None or event is None or not self._is_public(event, article):
            return None
        if live_content(self.session, article) is None:
            return None
        return event.id

    def _lookup(self, key: str) -> tuple[Article | None, Event | None]:
        try:
            public_id = UUID(key)
        except ValueError:
            article = self.articles.get_by_slug(key)
            if article is None:
                return None, None
            return article, self.events.get(article.event_id)
        event = self.events.get_by_public_id(public_id)
        if event is None:
            return None, None
        return self.articles.get_by_event_id(event.id), event

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
                selectinload(Event.claims)
                .selectinload(Claim.evidence)
                .selectinload(ClaimEvidence.source_item)
                .selectinload(SourceItem.source),
            )
            .where(Event.id == event_id)
        )
        return self.session.scalars(stmt).first()

    def _load_public(self, *, cap: int | None = PUBLIC_CANDIDATE_CAP) -> list[tuple[Event, Article, ArticleVersion]]:
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
        )
        if cap is not None:
            stmt = stmt.limit(cap)
        return [(event, article, live_row) for event, article, live_row in self.session.execute(stmt)]

    def _sorted_feed(
        self,
        *,
        sort: str,
        locality: str | None,
        limit: int,
        cursor: str | None,
        reader_id: UUID | None,
    ) -> dict:
        mode = sort.casefold().strip()
        if mode not in {"principal", "latest"}:
            raise ValueError("invalid_sort")
        now = utc_now()
        if cursor:
            as_of, after_id = _decode_home_cursor(
                cursor,
                now=now,
                max_age=self.settings.feed_cursor_max_age_seconds,
            )
        else:
            as_of, after_id = now, None
        rows = self._load_public(cap=None)
        if mode == "latest":
            ordered = sorted(rows, key=lambda row: (-_timestamp(row[1].published_at), str(row[1].id)))
        else:
            ordered = self._rank_principal(rows, locality=locality, reader_id=reader_id, as_of=as_of)
        start = 0
        if after_id is not None:
            found = next((index + 1 for index, row in enumerate(ordered) if row[1].id == after_id), None)
            if found is None:
                raise ValueError("invalid_cursor")
            start = found
        window = ordered[start : start + limit]
        items = [card_payload(event, article, live, session=self.session) for event, article, live in window]
        next_cursor = (
            _encode_home_cursor(as_of, window[-1][1].id)
            if len(window) == limit and start + limit < len(ordered)
            else None
        )
        return {"items": items, "next_cursor": next_cursor}

    def _rank_principal(
        self,
        rows: list[tuple[Event, Article, ArticleVersion]],
        *,
        locality: str | None,
        reader_id: UUID | None,
        as_of: datetime,
    ) -> list[tuple[Event, Article, ArticleVersion]]:
        weights = _principal_weights(self.settings)
        locality_selected = bool((locality or "").strip())
        place = (
            resolve_place([(event.country_code, event.province, event.locality) for event, _article, _live in rows], locality)
            if locality_selected
            else None
        )
        profile = empty_profile()
        if reader_id is not None:
            reads, likes = signal_ids(
                self.session,
                reader_id,
                since=as_of - timedelta(days=self.settings.feed_signal_window_days),
            )
            public_ids = {event.id for event, _article, _live in rows}
            event_types = {
                event.id: event.event_type
                for event, _article, _live in rows
                if event.id in reads or event.id in likes
            }
            profile = build_profile(event_types, reads & public_ids, likes & public_ids, weights=weights)
        scored: list[tuple[float, datetime, Event, Article, ArticleVersion]] = []
        for event, article, live in rows:
            reference = principal_reference(event.last_material_update_at, article.published_at)
            unit = relevance_unit(event.relevance_score, missing=weights.missing_relevance)
            fresh = freshness_unit(reference, as_of, halflife_hours=weights.freshness_halflife_hours)
            near = proximity(event.country_code, event.province, event.locality, place)
            base = base_score(
                relevance=unit,
                freshness=fresh,
                proximity_value=near,
                locality_selected=locality_selected,
                weights=weights,
            )
            score = principal_score(base, profile, event.event_type, weights=weights)
            scored.append((score, reference or article.published_at or as_of, event, article, live))
        scored.sort(key=lambda row: (-row[0], -_timestamp(row[1]), str(row[3].id)))
        return [(event, article, live) for _score, _tie, event, article, live in scored]

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
        items = [
            card_payload(event, article, live, score=round(score, 6), session=self.session)
            for score, article, event, live in window
        ]
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
        items = [card_payload(event, article, live, session=self.session) for event, article, live in window]
        next_cursor = str(window[-1][1].id) if len(window) == limit and start + limit < len(rows) else None
        return items, next_cursor


def _decode_id_cursor(cursor: str) -> UUID:
    try:
        return UUID(cursor)
    except ValueError as exc:
        raise ValueError("invalid_cursor") from exc


def _timestamp(value: datetime | None) -> float:
    if value is None:
        return 0.0
    return value.timestamp()


def _principal_weights(settings: Settings) -> PrincipalWeights:
    return PrincipalWeights(
        relevance=settings.feed_principal_relevance_weight,
        freshness=settings.feed_principal_freshness_weight,
        locality=settings.feed_principal_locality_weight,
        affinity_boost=settings.feed_affinity_boost,
        confidence_events=settings.feed_affinity_confidence_events,
        read_weight=settings.feed_read_weight,
        like_weight=settings.feed_like_weight,
        freshness_halflife_hours=settings.feed_freshness_halflife_hours,
        missing_relevance=settings.feed_missing_relevance,
    )


def _encode_home_cursor(as_of: datetime, article_id: UUID) -> str:
    return f"h1.{int(as_of.timestamp())}.{article_id}"


def _decode_home_cursor(cursor: str, *, now: datetime, max_age: int) -> tuple[datetime, UUID]:
    parts = cursor.split(".")
    if len(parts) != 3 or parts[0] != "h1":
        raise ValueError("invalid_cursor")
    try:
        stamp = int(parts[1])
        article_id = UUID(parts[2])
    except ValueError as exc:
        raise ValueError("invalid_cursor") from exc
    as_of = datetime.fromtimestamp(stamp, tz=timezone.utc)
    if as_of > now + timedelta(seconds=60) or (now - as_of).total_seconds() > max_age:
        raise ValueError("invalid_cursor")
    return as_of, article_id
