"""Qué republicación merece una entrada pública nueva."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.article import ArticleVersion

_MATCH_WINDOW = timedelta(seconds=5)


def _norm(value: str | None) -> str:
    return " ".join((value or "").split())


def same_published_text(previous: ArticleVersion | None, current: ArticleVersion | None) -> bool:
    if previous is None or current is None:
        return False
    return (
        _norm(previous.headline) == _norm(current.headline)
        and _norm(previous.summary) == _norm(current.summary)
        and _norm(previous.body) == _norm(current.body)
    )


def material_notice(previous: ArticleVersion | None, current: ArticleVersion | None) -> str | None:
    if previous is None or current is None or same_published_text(previous, current):
        return None
    changed: list[str] = []
    if _norm(previous.headline) != _norm(current.headline):
        changed.append("el titular")
    if _norm(previous.summary) != _norm(current.summary):
        changed.append("la bajada")
    if _norm(previous.body) != _norm(current.body):
        changed.append("el texto")
    if not changed:
        return "Actualización del artículo."
    if len(changed) == 1:
        return f"Actualización: cambió {changed[0]}."
    return f"Actualización: cambió {', '.join(changed[:-1])} y {changed[-1]}."


def version_matching(session: Session, article_id, occurred_at: datetime) -> ArticleVersion | None:
    versions = session.scalars(
        select(ArticleVersion)
        .where(ArticleVersion.article_id == article_id)
        .order_by(ArticleVersion.version_number.asc())
    ).all()
    match: ArticleVersion | None = None
    best: timedelta | None = None
    for version in versions:
        published_at = version.published_at
        if published_at is None:
            continue
        delta = abs(published_at - occurred_at)
        if delta <= _MATCH_WINDOW and (best is None or delta < best):
            match = version
            best = delta
    return match


def previous_published(session: Session, current: ArticleVersion) -> ArticleVersion | None:
    versions = session.scalars(
        select(ArticleVersion)
        .where(ArticleVersion.article_id == current.article_id)
        .where(ArticleVersion.version_number < current.version_number)
        .where(ArticleVersion.published_at.is_not(None))
        .order_by(ArticleVersion.version_number.desc())
    ).all()
    return versions[0] if versions else None


def public_update_notice(session: Session, article_id, occurred_at: datetime, stored: str | None) -> str | None:
    """None significa que la fila no aporta novedad y no debe mostrarse.

    Una cadena vacía no se usa: el aviso es texto o la fila se oculta.
    Si no hay versión comparable, se conserva la fila para no esconder historial.
    """
    if stored:
        return stored
    current = version_matching(session, article_id, occurred_at)
    if current is None:
        return ""
    previous = previous_published(session, current)
    if previous is None:
        return ""
    if same_published_text(previous, current):
        return None
    return material_notice(previous, current) or ""
