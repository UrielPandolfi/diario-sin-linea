"""Agregados de redacción para Admin. Solo lectura: no encola ni muta el pipeline."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.clock import utc_now
from app.domain.enums import ArticleStatus, EditorialLabel, EventStatus
from app.models import Article, Claim, Event, EventSource, SourceItem
from app.repositories import PipelineRunRepository, SourceItemRepository, SourceRepository
from app.services.editorial_label_policy import labels_for_event_claims
from app.services.publication_outcome import (
    CODE_LABELS,
    OUTCOME_CREATED,
    OUTCOME_DISCARDED,
    OUTCOME_LABELS,
    OUTCOME_LINKED,
    outcome_from_detection_run,
    summarize_detection_outcomes,
    writing_no_material_change,
)
from app.services.verification_outcome import verification_view_for_event

WINDOWS = {"24h": timedelta(hours=24), "7d": timedelta(days=7), "all": None}
_EPOCH = datetime(2000, 1, 1, tzinfo=timezone.utc)
_DETECTION_RUN_CAP = 10_000

_CLAIM_STATUS_LABELS = {
    "SUPPORTED": "Sostenido",
    "SINGLE_SOURCE": "Independencia desconocida",
    "CONFLICTING": "En conflicto",
    "UNCERTAIN": "Incierto",
    "DISPROVEN": "Desmentido",
    "OUTDATED": "Desactualizado",
}
_EDITORIAL_LABELS = {
    EditorialLabel.CHECKED.value: "Chequeado",
    EditorialLabel.DISCREPANCY.value: "Discrepancia entre medios",
    EditorialLabel.DISPUTED.value: "En disputa",
    EditorialLabel.FALSE_CLAIM.value: "Afirmación falsa",
}
_RELATION_LABELS = {
    "INITIAL": "Fuente inicial",
    "CONFIRMING": "Confirmación",
    "ADDITIONAL": "Adicional",
    "CONTRADICTING": "Contradice",
    "CORRECTING": "Corrige",
    "REPEATING": "Repite",
}


def _window_since(window: str) -> datetime | None:
    delta = WINDOWS.get(window, WINDOWS["all"])
    if delta is None:
        return None
    return utc_now() - delta


def _effective(since: datetime | None) -> datetime:
    return since or _EPOCH


def _enum_value(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _count(session: Session, stmt) -> int:
    return int(session.execute(stmt).scalar_one())


def _group_counts(rows: list[tuple[Any, int]]) -> list[dict[str, Any]]:
    return [{"key": _enum_value(key), "count": int(count)} for key, count in rows if key is not None]


class EditorialAnalyticsService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def snapshot(self, *, window: str = "all") -> dict[str, Any]:
        if window not in WINDOWS:
            window = "all"
        since = _window_since(window)
        detection = self._detection(since)
        published = self._published(since)
        claims = self._claims_on_published(since)
        labels = self._editorial_labels(since)
        funnel = {
            "notes_ingested": self._notes_ingested(since),
            "notes_by_status": self._notes_by_status(),
            "notes_discarded_not_news": detection["discarded_unique"],
            "notes_linked_existing": detection["linked_unique"],
            "sucesos_created": detection["created_unique"],
            "sucesos_total": self._events_count(since),
            "articles_published": published["published"],
            "articles_updated_track_b": published["updated_track_b"],
            "ready_for_review": published["ready_for_review"],
        }
        return {
            "window": window,
            "since": since.isoformat() if since else None,
            "read_only": True,
            "funnel": funnel,
            "detection": detection,
            "publication": published,
            "claims": claims,
            "editorial_labels": labels,
            "sources": self._sources(since),
            "headline": self._headline(funnel, detection, published, labels),
        }

    def _notes_ingested(self, since: datetime | None) -> int:
        stmt = select(func.count()).select_from(SourceItem)
        if since is not None:
            stmt = stmt.where(SourceItem.detected_at >= since)
        return _count(self.session, stmt)

    def _notes_by_status(self) -> list[dict[str, Any]]:
        rows = SourceItemRepository(self.session).count_by_status()
        return [{"key": key, "count": count} for key, count in sorted(rows.items())]

    def _events_count(self, since: datetime | None) -> int:
        stmt = select(func.count()).select_from(Event)
        if since is not None:
            stmt = stmt.where(Event.detected_at >= since)
        return _count(self.session, stmt)

    def _detection(self, since: datetime | None) -> dict[str, Any]:
        pipeline = PipelineRunRepository(self.session)
        start = _effective(since)
        counts = pipeline.detection_counts_in_range(since=start)
        runs = pipeline.list_detection_in_range(since=start, limit=_DETECTION_RUN_CAP)
        outcomes = [outcome_from_detection_run(run) for run in runs]
        by_outcome = summarize_detection_outcomes(outcomes)
        unique_family: dict[str, set[str]] = defaultdict(set)
        unique_code: dict[str, set[str]] = defaultdict(set)
        for run, outcome in zip(runs, outcomes):
            item_id = str(run.source_item_id) if run.source_item_id is not None else str(run.id)
            unique_family[outcome.outcome].add(item_id)
            unique_code[outcome.code].add(item_id)
        for family, bucket in by_outcome.items():
            bucket["unique_items"] = len(unique_family.get(family, ()))
        discarded = by_outcome.get(OUTCOME_DISCARDED, {})
        discarded_codes = [
            {**row, "unique_items": len(unique_code.get(row["code"], ()))}
            for row in (discarded.get("codes") or [])
        ]
        return {
            "attempts": counts["attempts"],
            "unique_items": counts["unique_items"],
            "truncated": counts["attempts"] > len(runs),
            "by_outcome": by_outcome,
            "discarded_codes": discarded_codes,
            "discarded_unique": len(unique_family.get(OUTCOME_DISCARDED, ())),
            "linked_unique": len(unique_family.get(OUTCOME_LINKED, ())),
            "created_unique": len(unique_family.get(OUTCOME_CREATED, ())),
            "outcome_labels": OUTCOME_LABELS,
            "code_labels": CODE_LABELS,
        }

    def _published(self, since: datetime | None) -> dict[str, Any]:
        published_filter = [Article.published_version.isnot(None)]
        if since is not None:
            published_filter.append(Article.published_at >= since)
        published = _count(
            self.session, select(func.count()).select_from(Article).where(*published_filter)
        )
        updated = _count(
            self.session,
            select(func.count())
            .select_from(Article)
            .where(*published_filter, Article.published_version >= 2),
        )
        ready = _count(
            self.session,
            select(func.count())
            .select_from(Article)
            .where(Article.status == ArticleStatus.READY_FOR_REVIEW),
        )
        event_filters = [Event.status == EventStatus.PUBLISHED]
        if since is not None:
            event_filters.append(Event.detected_at >= since)
        events_published = _count(
            self.session, select(func.count()).select_from(Event).where(*event_filters)
        )
        writing_runs = PipelineRunRepository(self.session).list_stage_in_range(
            "writing", since=_effective(since), limit=_DETECTION_RUN_CAP
        )
        no_material = 0
        material = 0
        reason_counts: dict[str, int] = defaultdict(int)
        for run in writing_runs:
            if writing_no_material_change(run):
                no_material += 1
                continue
            meta = run.metadata_json if isinstance(run.metadata_json, dict) else {}
            reasons = meta.get("material_reasons") or []
            if isinstance(reasons, list) and reasons:
                material += 1
                for reason in reasons:
                    if isinstance(reason, str) and reason.strip():
                        reason_counts[reason] += 1
        return {
            "published": published,
            "updated_track_b": updated,
            "ready_for_review": ready,
            "events_published_status": events_published,
            "writing_material_updates": material,
            "writing_no_material_change": no_material,
            "material_reasons": [
                {"key": key, "count": count} for key, count in sorted(reason_counts.items())
            ],
        }

    def _claims_on_published(self, since: datetime | None) -> dict[str, Any]:
        stmt = (
            select(Claim.status, func.count())
            .join(Article, Article.event_id == Claim.event_id)
            .where(Article.published_version.isnot(None))
            .group_by(Claim.status)
        )
        if since is not None:
            stmt = stmt.where(Article.published_at >= since)
        rows = _group_counts(list(self.session.execute(stmt)))
        labeled = [
            {**row, "label": _CLAIM_STATUS_LABELS.get(row["key"], row["key"])} for row in rows
        ]
        return {
            "total": sum(row["count"] for row in labeled),
            "by_status": labeled,
        }

    def _editorial_labels(self, since: datetime | None) -> dict[str, Any]:
        stmt = (
            select(Event)
            .join(Article, Article.event_id == Event.id)
            .where(Article.published_version.isnot(None))
            .options(selectinload(Event.claims).selectinload(Claim.evidence))
        )
        if since is not None:
            stmt = stmt.where(Article.published_at >= since)
        events = list(self.session.scalars(stmt).unique().all())
        articles_with: dict[str, int] = {key: 0 for key in _EDITORIAL_LABELS}
        claims_with: dict[str, int] = {key: 0 for key in _EDITORIAL_LABELS}
        for event in events:
            _, view = verification_view_for_event(self.session, event.id)
            editorials = labels_for_event_claims(list(event.claims), view)
            present: set[str] = set()
            for editorial in editorials.values():
                for label in editorial.labels:
                    key = label.value
                    claims_with[key] = claims_with.get(key, 0) + 1
                    present.add(key)
            for key in present:
                articles_with[key] = articles_with.get(key, 0) + 1
        return {
            "published_notes_scored": len(events),
            "on_articles": [
                {"key": key, "label": _EDITORIAL_LABELS[key], "count": articles_with[key]}
                for key in _EDITORIAL_LABELS
            ],
            "on_claims": [
                {"key": key, "label": _EDITORIAL_LABELS[key], "count": claims_with[key]}
                for key in _EDITORIAL_LABELS
            ],
        }

    def _sources(self, since: datetime | None) -> dict[str, Any]:
        stmt = select(EventSource.relation_type, func.count()).group_by(EventSource.relation_type)
        if since is not None:
            stmt = stmt.where(EventSource.added_at >= since)
        rows = _group_counts(list(self.session.execute(stmt)))
        return {
            "monitored": SourceRepository(self.session).count_monitored(),
            "by_relation": [
                {**row, "label": _RELATION_LABELS.get(row["key"], row["key"])} for row in rows
            ],
        }

    def _headline(
        self,
        funnel: dict[str, Any],
        detection: dict[str, Any],
        published: dict[str, Any],
        labels: dict[str, Any],
    ) -> list[str]:
        discrepancy = next(
            (
                row["count"]
                for row in labels["on_articles"]
                if row["key"] == EditorialLabel.DISCREPANCY.value
            ),
            0,
        )
        checked = next(
            (
                row["count"]
                for row in labels["on_articles"]
                if row["key"] == EditorialLabel.CHECKED.value
            ),
            0,
        )
        lines = [
            f"Leímos {funnel['notes_ingested']} notas de fuentes vigiladas.",
            f"{detection['discarded_unique']} no calificaban como noticia de alcance editorial.",
            f"{detection['created_unique']} abrieron un suceso nuevo.",
            f"{detection['linked_unique']} se vincularon a un suceso que ya existía.",
            f"Publicamos {published['published']} notas.",
            f"{published['updated_track_b']} se actualizaron con información posterior (Track B).",
        ]
        if labels["published_notes_scored"]:
            lines.append(
                f"En {discrepancy} de las publicadas encontramos discrepancias entre medios."
            )
            lines.append(f"{checked} notas publicadas tienen claims chequeados.")
        return lines
