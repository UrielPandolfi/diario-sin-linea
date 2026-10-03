"""Lectura de borradores cuya evaluación vigente impide aprobarlos.

No encola pipeline ni reevalúa. Una fila por artículo: la candidata actual,
con el último auditing concluido de esa versión.
"""

from __future__ import annotations

import base64
import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.article_body import claim_ids_in_body_blocks
from app.domain.enums import ArticleStatus, EventStatus, PipelineStatus
from app.models import Article, ArticleVersion, Claim, Event, PipelineRun
from app.schemas.auditing import AuditIssue
from app.services.audit_policy import (
    apply_headline_attribution_tolerance,
    blocking_issues,
    drop_attributed_single_as_corroborated,
    drop_mismatched_llm_claim_links,
)
from app.services.evidence_snapshot import evidence_snapshot_for_version
from app.services.pipeline_lock import AUDITING_STAGE, PUBLISHING_STAGE, WRITING_STAGE
from app.services.source_labels import public_source_name, public_source_title

DRAFT_LABEL = "Borrador no aprobado"
UPDATE_LABEL = "Actualización no aprobada"

_PIPELINE_STAGES = (WRITING_STAGE, AUDITING_STAGE, PUBLISHING_STAGE)
_BUSY = {PipelineStatus.RUNNING, PipelineStatus.RETRY}
_DONE = {PipelineStatus.SUCCESS, PipelineStatus.FAILED}
_INTERNAL_FRAGMENT = ("snapshot", "claim_id", "body_blocks", "coverage_gap", "pipeline", "version_after")
_UUID_FRAGMENT = re.compile(r"^[0-9a-f-]{32,}$", re.IGNORECASE)

GENERAL_REASON = {
    "category": "general",
    "text": (
        "Esta versión no superó los controles editoriales. El registro no detalla una causa más específica. "
        "Eso no alcanza para afirmar que una noticia ya publicada sea falsa."
    ),
}
TECHNICAL_REASON = {
    "category": "technical",
    "text": (
        "La evaluación de esta versión se interrumpió por un fallo técnico. "
        "No es un resultado sobre la veracidad del texto."
    ),
}

_REASON_COPY: dict[str, tuple[str, str]] = {
    "contract_missing": (
        "incomplete_verification",
        "La verificación de esta versión no quedó cerrada: falta el contraste entre sus afirmaciones y las fuentes de este borrador.",
    ),
    "contract_unpaired": (
        "incomplete_verification",
        "La verificación de esta versión está incompleta: las afirmaciones y su contraste no forman un par vigente.",
    ),
    "central_unverified": (
        "incomplete_verification",
        "Hay afirmaciones centrales de este borrador que no tienen una verificación concluida.",
    ),
    "central_uncovered": (
        "incomplete_verification",
        "El borrador sostiene algo central que no quedó cubierto por las afirmaciones verificadas de esta versión.",
    ),
    "headline_uncovered": (
        "incomplete_verification",
        "El titular de este borrador no quedó cubierto por las afirmaciones verificadas de esta versión.",
    ),
    "surface_contract_incomplete": (
        "incomplete_verification",
        "Una frase del borrador va más allá de lo que la verificación de esta versión permite afirmar.",
    ),
    "surface_indeterminate": (
        "incomplete_verification",
        "No se pudo determinar si una frase del borrador respeta el resultado de la verificación de esta versión.",
    ),
    "unbacked_material": (
        "missing_support",
        "Una afirmación de este borrador no tiene respaldo en las fuentes de esta versión.",
    ),
    "partial_as_total": (
        "missing_support",
        "El borrador presenta como completo algo que las fuentes de esta versión solo respaldan en parte.",
    ),
    "invalid_claim_ref": (
        "missing_support",
        "El borrador enlaza una afirmación que no pertenece a la verificación de esta versión.",
    ),
    "attribution_lost": (
        "attribution",
        "El borrador pierde la atribución que exigía la verificación de esta versión.",
    ),
    "surface_attribution": (
        "attribution",
        "Falta atribuir una afirmación a quien corresponde según la verificación de esta versión.",
    ),
    "utterance_as_truth": (
        "attribution",
        "El borrador presenta como hecho algo que en esta versión solo consta como dicho de una fuente.",
    ),
    "accusation_as_fact": (
        "attribution",
        "Una acusación figura como hecho, sin la atribución que exige esta versión.",
    ),
    "norm_effective_as_fact": (
        "attribution",
        "El borrador da por vigente o efectiva una norma más allá de lo verificado en esta versión.",
    ),
    "single_as_corroborated": (
        "overcertainty",
        "El borrador afirma con más certeza de la que permite el respaldo de esta versión.",
    ),
    "surface_categorical": (
        "overcertainty",
        "El borrador presenta como hecho seguro algo que esta versión no permite afirmar así.",
    ),
    "surface_independent_language": (
        "overcertainty",
        "El borrador habla de fuentes independientes más allá de lo que muestra esta versión.",
    ),
    "semantic_shift": (
        "overcertainty",
        "Una frase del borrador cambia el sentido de lo que las fuentes de esta versión respaldan.",
    ),
}

_TYPE_COPY: dict[str, tuple[str, str]] = {
    "UNSUPPORTED_CLAIM": (
        "missing_support",
        "Una afirmación de este borrador no tiene respaldo suficiente en esta versión.",
    ),
    "NUMBER": (
        "missing_support",
        "Una cifra del borrador no queda respaldada por la verificación de esta versión.",
    ),
    "NAME": (
        "missing_support",
        "Un nombre del borrador no queda respaldado por la verificación de esta versión.",
    ),
    "DATE": (
        "missing_support",
        "Una fecha del borrador no queda respaldada por la verificación de esta versión.",
    ),
    "ATTRIBUTION": (
        "attribution",
        "Hay un problema de atribución en este borrador respecto de la verificación de esta versión.",
    ),
    "UNATTRIBUTED_CHARACTERIZATION": (
        "attribution",
        "El borrador califica algo sin la atribución que exige esta versión.",
    ),
    "CONTRADICTION": (
        "missing_support",
        "El borrador afirma algo que no cierra con lo verificado en esta versión.",
    ),
    "CAUSALITY": (
        "overcertainty",
        "El borrador presenta una causa o una consecuencia con más certeza de la que permite esta versión.",
    ),
    "INFERENCE": (
        "overcertainty",
        "El borrador presenta una inferencia como si fuera un hecho verificado.",
    ),
    "FRAMING": (
        "overcertainty",
        "El encuadre del borrador va más allá de lo que esta versión puede afirmar.",
    ),
    "ADJECTIVE": (
        "overcertainty",
        "El borrador usa una calificación que esta versión no respalda.",
    ),
    "MATERIAL_OMISSION": (
        "incomplete_verification",
        "Falta un dato que el control de esta versión considera necesario para publicar.",
    ),
    "INVALID_CLAIM_MAPPING": (
        "missing_support",
        "El borrador enlaza una afirmación que no pertenece a la verificación de esta versión.",
    ),
    "UNMAPPED_MATERIAL_CLAIM": (
        "missing_support",
        "Hay una afirmación material de este borrador que no está en la verificación de esta versión.",
    ),
    "REDUNDANCY": (
        "general",
        "El control editorial marcó un problema de redacción en esta versión. No es una conclusión sobre la veracidad del texto.",
    ),
    "CLARITY": (
        "general",
        "El control editorial marcó un problema de claridad en esta versión. No es una conclusión sobre la veracidad del texto.",
    ),
}


def has_full_draft_text(version: ArticleVersion | None) -> bool:
    if version is None:
        return False
    return bool(
        (version.headline or "").strip()
        and (version.summary or "").strip()
        and (version.body or "").strip()
    )


def pipeline_busy(runs: list[PipelineRun]) -> bool:
    return any(run.stage in _PIPELINE_STAGES and run.status in _BUSY for run in runs)


def version_binding(meta: dict[str, Any] | None) -> int | None:
    raw = (meta or {}).get("version_after")
    if raw is None:
        snap = (meta or {}).get("evidence_snapshot")
        if isinstance(snap, dict):
            raw = snap.get("version")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def audit_approved(meta: dict[str, Any] | None) -> bool:
    passed = (meta or {}).get("passed")
    return passed is True or passed == "true"


def governing_audit(runs: list[PipelineRun], version: int) -> PipelineRun | None:
    """Última evaluación concluida de `version`. Un passed posterior anula un rechazo previo."""
    audits = sorted(
        (run for run in runs if run.stage == AUDITING_STAGE and run.status in _DONE),
        key=_started,
        reverse=True,
    )
    bound = [run for run in audits if version_binding(run.metadata_json) == int(version)]
    if bound:
        return bound[0]
    if not audits:
        return None
    latest = audits[0]
    if version_binding(latest.metadata_json) not in (None, int(version)):
        return None
    if not _technical_failure(latest):
        return None
    writing = _writing_for_version(runs, version)
    if writing is None or writing.started_at is None or latest.started_at is None:
        return None
    if latest.started_at < writing.started_at:
        return None
    return latest


def rejection_mode(run: PipelineRun | None) -> str | None:
    if run is None:
        return None
    meta = run.metadata_json or {}
    if audit_approved(meta):
        return None
    if meta.get("audited") is True and (meta.get("passed") is False or meta.get("passed") == "false"):
        return "editorial"
    if _technical_failure(run):
        return "technical"
    return None


def reader_reasons(
    raw_issues: Any,
    *,
    article: Any,
    snapshot: dict[str, Any] | None,
    mode: str,
) -> list[dict[str, str]]:
    if mode == "technical":
        return [dict(TECHNICAL_REASON)]
    blocking = current_blocking_issues(raw_issues, article=article, snapshot=snapshot)
    reasons: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for issue in blocking:
        item = _explain_issue(issue)
        if item is None:
            continue
        key = (item["category"], item["text"])
        if key in seen:
            continue
        seen.add(key)
        reasons.append(item)
    if not reasons:
        return [dict(GENERAL_REASON)]
    return reasons


def current_blocking_issues(
    raw_issues: Any,
    *,
    article: Any,
    snapshot: dict[str, Any] | None,
) -> list[AuditIssue]:
    parsed: list[AuditIssue] = []
    if isinstance(raw_issues, list):
        for row in raw_issues:
            if not isinstance(row, dict):
                continue
            try:
                parsed.append(AuditIssue.model_validate(row))
            except ValueError:
                continue
    if article is not None:
        parsed = drop_attributed_single_as_corroborated(parsed, article)
    parsed = drop_mismatched_llm_claim_links(parsed, snapshot)
    parsed = apply_headline_attribution_tolerance(
        parsed,
        article,
        snapshot if isinstance(snapshot, dict) else None,
    )
    return blocking_issues(parsed)


def snapshot_sources(snapshot: dict[str, Any] | None) -> list[dict[str, Any]]:
    context = snapshot.get("article_context") if isinstance(snapshot, dict) else None
    if not isinstance(context, dict):
        return []
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in context.get("sources") or []:
        if not isinstance(row, dict):
            continue
        url = row.get("url")
        name = public_source_name(
            row.get("name") if isinstance(row.get("name"), str) else None,
            row.get("domain") if isinstance(row.get("domain"), str) else None,
        )
        key = str(url or name)
        if key in seen:
            continue
        seen.add(key)
        title = row.get("title") if isinstance(row.get("title"), str) else None
        domain = row.get("domain") if isinstance(row.get("domain"), str) else None
        rows.append(
            {
                "name": name,
                "domain": domain,
                "url": url if isinstance(url, str) else None,
                "title": public_source_title(title),
            }
        )
    return rows


class RejectedDraftQuery:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_page(self, *, limit: int, cursor: str | None) -> dict[str, Any]:
        moment, article_id = _decode_cursor(cursor) if cursor else (None, None)
        rows = [row for row in self._collect() if row is not None]
        rows.sort(key=lambda row: str(row["id"]))
        rows.sort(key=lambda row: row["evaluated_at"], reverse=True)
        if moment is not None and article_id is not None:
            rows = [row for row in rows if _after(row, moment, article_id)]
        page = rows[:limit]
        next_cursor = None
        if len(rows) > limit and page:
            last = page[-1]
            next_cursor = _encode_cursor(last["evaluated_at"], UUID(str(last["id"])))
        return {
            "items": [_public_card(row) for row in page],
            "next_cursor": next_cursor,
        }

    def get(self, article_id: UUID) -> dict[str, Any] | None:
        pair = self._load_one(article_id)
        if pair is None:
            return None
        article, version = pair
        runs = self._runs_for([article.event_id]).get(article.event_id, [])
        row = _assess(article, version, runs)
        if row is None:
            return None
        event = self.session.scalars(
            select(Event)
            .options(selectinload(Event.claims).selectinload(Claim.evidence))
            .where(Event.id == article.event_id)
        ).first()
        from app.services.feed_ranking import compact_public_claims

        snapshot = row["snapshot"] if isinstance(row["snapshot"], dict) else None
        claims: list[dict] = []
        if event is not None and snapshot is not None:
            claims = compact_public_claims(
                self.session,
                event,
                allowed_ids=claim_ids_in_body_blocks(version.body_blocks),
                freeze_to_version=int(version.version_number),
            )
        return {
            **_public_card(row),
            "summary": version.summary,
            "body": version.body,
            "body_blocks": version.body_blocks,
            "reasons": row["reasons"],
            "sources": snapshot_sources(snapshot),
            "claims": claims,
        }

    def _collect(self) -> list[dict[str, Any] | None]:
        pairs = self._load_candidates()
        runs_by_event = self._runs_for([article.event_id for article, _version in pairs])
        return [_assess(article, version, runs_by_event.get(article.event_id, [])) for article, version in pairs]

    def _load_candidates(self) -> list[tuple[Article, ArticleVersion]]:
        stmt = (
            select(Article, ArticleVersion)
            .join(Event, Event.id == Article.event_id)
            .join(
                ArticleVersion,
                and_(
                    ArticleVersion.article_id == Article.id,
                    ArticleVersion.version_number == Article.current_version,
                ),
            )
            .where(
                Article.status != ArticleStatus.ARCHIVED,
                Event.status != EventStatus.ARCHIVED,
                or_(
                    Article.published_version.is_(None),
                    Article.published_version != Article.current_version,
                ),
            )
        )
        return [(article, version) for article, version in self.session.execute(stmt)]

    def _load_one(self, article_id: UUID) -> tuple[Article, ArticleVersion] | None:
        stmt = (
            select(Article, ArticleVersion)
            .join(Event, Event.id == Article.event_id)
            .join(
                ArticleVersion,
                and_(
                    ArticleVersion.article_id == Article.id,
                    ArticleVersion.version_number == Article.current_version,
                ),
            )
            .where(
                Article.id == article_id,
                Article.status != ArticleStatus.ARCHIVED,
                Event.status != EventStatus.ARCHIVED,
                or_(
                    Article.published_version.is_(None),
                    Article.published_version != Article.current_version,
                ),
            )
        )
        row = self.session.execute(stmt).first()
        if row is None:
            return None
        return row[0], row[1]

    def _runs_for(self, event_ids: list[UUID]) -> dict[UUID, list[PipelineRun]]:
        if not event_ids:
            return {}
        stmt = (
            select(PipelineRun)
            .where(
                PipelineRun.event_id.in_(event_ids),
                PipelineRun.stage.in_(_PIPELINE_STAGES),
            )
            .order_by(PipelineRun.started_at.desc())
        )
        grouped: dict[UUID, list[PipelineRun]] = {}
        for run in self.session.scalars(stmt):
            if run.event_id is None:
                continue
            grouped.setdefault(run.event_id, []).append(run)
        return grouped


def _assess(article: Article, version: ArticleVersion, runs: list[PipelineRun]) -> dict[str, Any] | None:
    runs = sorted(runs, key=_started, reverse=True)
    if pipeline_busy(runs) or not has_full_draft_text(version):
        return None
    if article.published_version is not None and int(article.published_version) == int(article.current_version):
        return None
    audit = governing_audit(runs, int(version.version_number))
    mode = rejection_mode(audit)
    if audit is None or mode is None:
        return None
    meta = audit.metadata_json or {}
    snapshot = meta.get("evidence_snapshot") if isinstance(meta.get("evidence_snapshot"), dict) else None
    if snapshot is None:
        snapshot = evidence_snapshot_for_version(runs, int(version.version_number))
    surface = _surface(version)
    reasons = reader_reasons(meta.get("issues"), article=surface, snapshot=snapshot, mode=mode)
    evaluated_at = _aware(audit.finished_at or audit.started_at)
    if evaluated_at is None:
        return None
    update = (
        article.published_version is not None
        and article.published_at is not None
        and int(article.published_version) != int(article.current_version)
    )
    return {
        "id": str(article.id),
        "headline": version.headline,
        "label": UPDATE_LABEL if update else DRAFT_LABEL,
        "evaluated_at": evaluated_at,
        "reason": reasons[0]["text"],
        "reasons": reasons,
        "published_path": f"/noticias/{article.slug}" if update and _safe_slug(article.slug) else None,
        "snapshot": snapshot,
    }


def _public_card(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "headline": row["headline"],
        "label": row["label"],
        "evaluated_at": row["evaluated_at"].isoformat(),
        "reason": row["reason"],
        "published_path": row["published_path"],
    }


def _surface(version: ArticleVersion) -> Any:
    from types import SimpleNamespace

    return SimpleNamespace(
        headline=version.headline,
        summary=version.summary,
        body=version.body,
        body_blocks=version.body_blocks,
    )


def _started(run: PipelineRun) -> datetime:
    value = run.started_at or datetime.min.replace(tzinfo=timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _writing_for_version(runs: list[PipelineRun], version: int) -> PipelineRun | None:
    ordered = sorted(runs, key=_started, reverse=True)
    for run in ordered:
        if run.stage != WRITING_STAGE or run.status != PipelineStatus.SUCCESS:
            continue
        meta = run.metadata_json or {}
        raw = meta.get("version")
        if raw is None:
            snap = meta.get("evidence_snapshot")
            if isinstance(snap, dict):
                raw = snap.get("version")
        try:
            if raw is not None and int(raw) == int(version):
                return run
        except (TypeError, ValueError):
            continue
    return None


def _technical_failure(run: PipelineRun) -> bool:
    meta = run.metadata_json or {}
    if audit_approved(meta):
        return False
    if run.status == PipelineStatus.FAILED and meta.get("audited") is not True:
        return True
    return meta.get("technical_ok") is False and meta.get("audited") is not True


def _explain_issue(issue: AuditIssue) -> dict[str, str] | None:
    reason = issue.reason.value if issue.reason is not None else None
    copy = _REASON_COPY.get(reason or "")
    if copy is None:
        copy = _TYPE_COPY.get(issue.type.value if issue.type is not None else "")
    if copy is None:
        return None
    category, sentence = copy
    fragment = _reader_fragment(issue.text)
    text = sentence
    if fragment and fragment.casefold() not in sentence.casefold():
        text = f"{sentence} En el borrador: «{fragment}»."
    return {"category": category, "text": text}


def _reader_fragment(text: str | None) -> str | None:
    cleaned = " ".join((text or "").split())
    if len(cleaned) < 8 or len(cleaned) > 180:
        return None
    folded = cleaned.casefold()
    if any(token in folded for token in _INTERNAL_FRAGMENT):
        return None
    if _UUID_FRAGMENT.fullmatch(folded):
        return None
    return cleaned


def _safe_slug(slug: str | None) -> bool:
    if not slug or slug.strip() != slug:
        return False
    if "/" in slug or "\\" in slug or slug.startswith("."):
        return False
    return "://" not in slug


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _after(row: dict[str, Any], moment: datetime, article_id: UUID) -> bool:
    when = row["evaluated_at"]
    if when < moment:
        return True
    if when == moment and str(row["id"]) > str(article_id):
        return True
    return False


def _encode_cursor(evaluated_at: datetime, article_id: UUID) -> str:
    raw = f"{evaluated_at.isoformat()}|{article_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def _decode_cursor(value: str) -> tuple[datetime, UUID]:
    padded = value + "=" * (-len(value) % 4)
    try:
        decoded = base64.urlsafe_b64decode(padded.encode()).decode()
        stamp, raw_id = decoded.split("|", 1)
        moment = datetime.fromisoformat(stamp)
    except (ValueError, UnicodeError):
        raise ValueError("invalid_cursor") from None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    try:
        return moment, UUID(raw_id)
    except ValueError:
        raise ValueError("invalid_cursor") from None
