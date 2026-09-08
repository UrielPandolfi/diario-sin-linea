"""Motivos de publicaciones a partir de ramas ya persistidas. Sin IA."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from app.core.source_content import body_source_from_item
from app.domain.enums import PipelineStatus, SourceItemStatus

DETECTION_STAGE = "event_detection"

OUTCOME_DISCARDED = "discarded"
OUTCOME_LINKED = "linked"
OUTCOME_CREATED = "created"
OUTCOME_ERROR = "error"
OUTCOME_PENDING = "pending"
OUTCOME_STAGE_SKIPPED = "stage_skipped"
OUTCOME_UNRECORDED = "unrecorded"

CODE_UNRECORDED = "UNRECORDED"
CODE_SPORTS_ONLY = "SPORTS_ONLY"
CODE_IRRELEVANT = "IRRELEVANT"
CODE_NOT_PUBLIC_AFFAIRS = "NOT_PUBLIC_AFFAIRS"
CODE_OUTSIDE_TARGET_COUNTRY = "OUTSIDE_TARGET_COUNTRY"
CODE_ALREADY_LINKED = "ALREADY_LINKED"
CODE_LEVEL1_URL = "LEVEL1_URL"
CODE_LEVEL1_CODE = "LEVEL1_CODE"
CODE_EMBEDDING_HIGH = "EMBEDDING_HIGH"
CODE_TERRA_EXISTING = "TERRA_EXISTING"
CODE_NO_CANDIDATES = "NO_CANDIDATES"
CODE_EMBEDDING_LOW = "EMBEDDING_LOW"
CODE_TERRA_NEW = "TERRA_NEW"
CODE_DETECTION_FAILED = "DETECTION_FAILED"
CODE_PROVIDER_NOT_CONFIGURED = "PROVIDER_NOT_CONFIGURED"
CODE_FETCH_FAILED = "FETCH_FAILED"
CODE_EMPTY_EXTRACT = "EMPTY_EXTRACT"
CODE_PENDING_DETECTION = "PENDING_DETECTION"
CODE_PENDING_QUOTA = "PENDING_QUOTA"
CODE_PROCESSING = "PROCESSING"
CODE_MAX_NEW_EVENTS = "MAX_NEW_EVENTS_PER_POLL"
CODE_NO_MATERIAL_CHANGE = "NO_MATERIAL_CHANGE"

OUTCOME_LABELS = {
    OUTCOME_DISCARDED: "Descartada",
    OUTCOME_LINKED: "Vinculada a un suceso",
    OUTCOME_CREATED: "Creó un suceso",
    OUTCOME_ERROR: "Error o lectura fallida",
    OUTCOME_PENDING: "Procesamiento pendiente",
    OUTCOME_STAGE_SKIPPED: "Etapa omitida",
    OUTCOME_UNRECORDED: "Sin motivo registrado",
}

CODE_LABELS = {
    CODE_SPORTS_ONLY: "Fuera de alcance: deporte",
    CODE_IRRELEVANT: "Fuera de alcance editorial",
    CODE_NOT_PUBLIC_AFFAIRS: "Fuera de alcance: no es asunto público",
    CODE_OUTSIDE_TARGET_COUNTRY: "Fuera de alcance: otro país",
    CODE_ALREADY_LINKED: "Ya vinculada al suceso",
    CODE_LEVEL1_URL: "Misma URL",
    CODE_LEVEL1_CODE: "Mismo suceso (datos coincidentes)",
    CODE_EMBEDDING_HIGH: "Mismo suceso (similitud alta)",
    CODE_TERRA_EXISTING: "Mismo suceso (deduplicación ambigua)",
    CODE_NO_CANDIDATES: "Suceso nuevo (sin candidatos)",
    CODE_EMBEDDING_LOW: "Suceso nuevo (similitud baja)",
    CODE_TERRA_NEW: "Suceso nuevo (deduplicación ambigua)",
    CODE_DETECTION_FAILED: "Error en detección",
    CODE_PROVIDER_NOT_CONFIGURED: "Proveedor no configurado",
    CODE_FETCH_FAILED: "No se pudo leer el artículo",
    CODE_EMPTY_EXTRACT: "Sin texto extraíble",
    CODE_PENDING_DETECTION: "Pendiente de detección",
    CODE_PENDING_QUOTA: "Pendiente por tope de poll",
    CODE_PROCESSING: "En proceso",
    CODE_MAX_NEW_EVENTS: "Tope de sucesos nuevos por poll",
    CODE_NO_MATERIAL_CHANGE: "Sin cambio material (redacción)",
    CODE_UNRECORDED: "Sin motivo registrado",
}

_REASON_CODES = {
    "sports_only": CODE_SPORTS_ONLY,
    "irrelevant": CODE_IRRELEVANT,
    "not_public_affairs": CODE_NOT_PUBLIC_AFFAIRS,
    "outside_target_country": CODE_OUTSIDE_TARGET_COUNTRY,
    "already_linked": CODE_ALREADY_LINKED,
    "level1_url": CODE_LEVEL1_URL,
    "level1_code": CODE_LEVEL1_CODE,
    "terra_existing": CODE_TERRA_EXISTING,
    "terra_new": CODE_TERRA_NEW,
    "no_candidates": CODE_NO_CANDIDATES,
    "max_new_events_per_poll": CODE_MAX_NEW_EVENTS,
    "failed": CODE_DETECTION_FAILED,
}

_DISCARDED_CODES = {
    CODE_SPORTS_ONLY,
    CODE_IRRELEVANT,
    CODE_NOT_PUBLIC_AFFAIRS,
    CODE_OUTSIDE_TARGET_COUNTRY,
}
_LINKED_CODES = {
    CODE_ALREADY_LINKED,
    CODE_LEVEL1_URL,
    CODE_LEVEL1_CODE,
    CODE_EMBEDDING_HIGH,
    CODE_TERRA_EXISTING,
}
_CREATED_CODES = {CODE_NO_CANDIDATES, CODE_EMBEDDING_LOW, CODE_TERRA_NEW}


@dataclass(frozen=True)
class PublicationOutcome:
    outcome: str
    code: str
    stage: str | None = DETECTION_STAGE
    event_ids: list[str] = field(default_factory=list)
    run_id: str | None = None
    finished_at: datetime | None = None
    started_at: datetime | None = None
    attempt: int | None = None
    trigger: str | None = None

    @property
    def outcome_label(self) -> str:
        return OUTCOME_LABELS.get(self.outcome, self.outcome)

    @property
    def code_label(self) -> str:
        return CODE_LABELS.get(self.code, self.code)

    def as_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "outcome_label": self.outcome_label,
            "code": self.code,
            "code_label": self.code_label,
            "stage": self.stage,
            "event_ids": list(self.event_ids),
            "run_id": self.run_id,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "attempt": self.attempt,
            "trigger": self.trigger,
        }


def _status_value(value: Any) -> str:
    if value is None:
        return ""
    return value.value if hasattr(value, "value") else str(value)


def _run_meta(run: Any) -> dict[str, Any]:
    if run is None:
        return {}
    meta = getattr(run, "metadata_json", None) or {}
    return meta if isinstance(meta, dict) else {}


def normalize_detection_code(raw: str | None) -> str | None:
    if not raw:
        return None
    text = str(raw).strip()
    if not text:
        return None
    lowered = text.lower()
    if lowered.startswith("embedding_high"):
        return CODE_EMBEDDING_HIGH
    if lowered.startswith("embedding_low"):
        return CODE_EMBEDDING_LOW
    mapped = _REASON_CODES.get(lowered) or _REASON_CODES.get(text)
    if mapped:
        return mapped
    upper = text.upper().replace("-", "_").replace(" ", "_")
    if upper in CODE_LABELS:
        return upper
    return None


def _unrecorded(*, event_ids: list[str], run: Any = None) -> PublicationOutcome:
    return PublicationOutcome(
        outcome=OUTCOME_UNRECORDED,
        code=CODE_UNRECORDED,
        event_ids=event_ids,
        run_id=str(run.id) if run is not None else None,
        finished_at=getattr(run, "finished_at", None) if run is not None else None,
        started_at=getattr(run, "started_at", None) if run is not None else None,
        attempt=getattr(run, "attempt", None) if run is not None else None,
        trigger=(_run_meta(run).get("trigger") if run is not None else None),
    )


def _with_run(outcome: str, code: str, run: Any, event_ids: list[str]) -> PublicationOutcome:
    meta = _run_meta(run)
    return PublicationOutcome(
        outcome=outcome,
        code=code,
        event_ids=event_ids,
        run_id=str(run.id) if run is not None else None,
        finished_at=getattr(run, "finished_at", None) if run is not None else None,
        started_at=getattr(run, "started_at", None) if run is not None else None,
        attempt=getattr(run, "attempt", None) if run is not None else None,
        trigger=meta.get("trigger") if isinstance(meta.get("trigger"), str) else None,
    )


def _is_provider_error(message: str | None) -> bool:
    text = (message or "").lower()
    return "provider" in text or "api key" in text or "falta" in text or "no configurado" in text


def outcome_from_detection_run(
    run: Any,
    *,
    linked_event_ids: list[str] | None = None,
) -> PublicationOutcome:
    """Una corrida de detección (estadísticas de período / historial)."""
    event_ids = [str(eid) for eid in (linked_event_ids or [])]
    run_event = getattr(run, "event_id", None)
    if run_event is not None and str(run_event) not in event_ids:
        event_ids = [*event_ids, str(run_event)]
    if run is None:
        return _unrecorded(event_ids=event_ids)

    meta = _run_meta(run)
    status = _status_value(getattr(run, "status", None))
    reason = meta.get("reason")
    filter_reason = meta.get("filter_reason")
    code = normalize_detection_code(filter_reason) or normalize_detection_code(
        reason if isinstance(reason, str) else None
    )

    if meta.get("filtered") or filter_reason:
        discarded = code if code in _DISCARDED_CODES else (code or CODE_UNRECORDED)
        family = OUTCOME_DISCARDED if discarded in _DISCARDED_CODES else OUTCOME_UNRECORDED
        return _with_run(family, discarded, run, event_ids)

    if meta.get("pipeline_skipped") or code == CODE_MAX_NEW_EVENTS:
        return _with_run(OUTCOME_STAGE_SKIPPED, CODE_MAX_NEW_EVENTS, run, event_ids)

    if status == PipelineStatus.FAILED.value:
        failed_code = (
            CODE_PROVIDER_NOT_CONFIGURED
            if _is_provider_error(getattr(run, "error_message", None))
            else CODE_DETECTION_FAILED
        )
        return _with_run(OUTCOME_ERROR, failed_code, run, event_ids)

    if status == PipelineStatus.RETRY.value:
        return _with_run(OUTCOME_PENDING, CODE_PENDING_DETECTION, run, event_ids)

    if status == PipelineStatus.RUNNING.value:
        return _with_run(OUTCOME_PENDING, CODE_PROCESSING, run, event_ids)

    if meta.get("created") is True:
        created_code = code if code in _CREATED_CODES else (code or CODE_UNRECORDED)
        family = OUTCOME_CREATED if created_code in _CREATED_CODES else OUTCOME_UNRECORDED
        return _with_run(family, created_code, run, event_ids)

    if meta.get("created") is False and code in _LINKED_CODES:
        return _with_run(OUTCOME_LINKED, code, run, event_ids)

    if code in _LINKED_CODES:
        return _with_run(OUTCOME_LINKED, code, run, event_ids)
    if code in _CREATED_CODES:
        return _with_run(OUTCOME_CREATED, code, run, event_ids)
    if code in _DISCARDED_CODES:
        return _with_run(OUTCOME_DISCARDED, code, run, event_ids)

    if event_ids and status == PipelineStatus.SUCCESS.value:
        return _with_run(OUTCOME_LINKED, code or CODE_ALREADY_LINKED, run, event_ids)

    return _unrecorded(event_ids=event_ids, run=run)


def current_item_outcome(
    item: Any,
    *,
    latest_run: Any | None,
    linked_event_ids: list[str],
) -> PublicationOutcome:
    """Estado actual de un SourceItem (listado). Conserva historial en otras corridas."""
    status = _status_value(getattr(item, "processing_status", None))
    event_ids = [str(eid) for eid in linked_event_ids]

    if latest_run is not None:
        mapped = outcome_from_detection_run(latest_run, linked_event_ids=event_ids)
        if mapped.outcome != OUTCOME_UNRECORDED or mapped.code != CODE_UNRECORDED:
            if mapped.outcome == OUTCOME_STAGE_SKIPPED and mapped.code == CODE_MAX_NEW_EVENTS:
                if status in {
                    SourceItemStatus.PENDING.value,
                    SourceItemStatus.PROCESSING.value,
                }:
                    return PublicationOutcome(
                        outcome=OUTCOME_PENDING,
                        code=CODE_PENDING_QUOTA,
                        event_ids=event_ids,
                        run_id=mapped.run_id,
                        finished_at=mapped.finished_at,
                        started_at=mapped.started_at,
                        attempt=mapped.attempt,
                        trigger=mapped.trigger,
                    )
                return mapped
            if mapped.outcome == OUTCOME_PENDING and event_ids and status != SourceItemStatus.FAILED.value:
                if mapped.code in {CODE_PENDING_QUOTA, CODE_MAX_NEW_EVENTS}:
                    return mapped
                return PublicationOutcome(
                    outcome=OUTCOME_LINKED,
                    code=CODE_ALREADY_LINKED,
                    event_ids=event_ids,
                    run_id=mapped.run_id,
                    finished_at=mapped.finished_at,
                    started_at=mapped.started_at,
                    attempt=mapped.attempt,
                    trigger=mapped.trigger,
                )
            return mapped

    if event_ids and status != SourceItemStatus.FAILED.value:
        return PublicationOutcome(
            outcome=OUTCOME_LINKED,
            code=CODE_ALREADY_LINKED,
            event_ids=event_ids,
        )

    if status == SourceItemStatus.PROCESSING.value:
        return PublicationOutcome(outcome=OUTCOME_PENDING, code=CODE_PROCESSING, event_ids=event_ids)
    if status == SourceItemStatus.PENDING.value:
        return PublicationOutcome(
            outcome=OUTCOME_PENDING, code=CODE_PENDING_DETECTION, event_ids=event_ids
        )
    if status == SourceItemStatus.FAILED.value:
        return PublicationOutcome(
            outcome=OUTCOME_ERROR, code=CODE_DETECTION_FAILED, event_ids=event_ids
        )
    if status == SourceItemStatus.SKIPPED.value:
        return _unrecorded(event_ids=event_ids, run=latest_run)
    return _unrecorded(event_ids=event_ids, run=latest_run)


def writing_no_material_change(run: Any) -> bool:
    if run is None or getattr(run, "stage", None) != "writing":
        return False
    return _run_meta(run).get("reason") == "no_material_change"


def item_publication_payload(
    item: Any,
    *,
    latest_run: Any | None,
    linked_event_ids: list[str],
    source_name: str | None = None,
) -> dict[str, Any]:
    outcome = current_item_outcome(
        item, latest_run=latest_run, linked_event_ids=linked_event_ids
    )
    meta = getattr(item, "metadata_json", None) or {}
    return {
        "id": str(item.id),
        "source_id": str(item.source_id),
        "source_name": source_name,
        "url": item.url,
        "canonical_url": item.canonical_url,
        "title": item.title,
        "published_at": item.published_at.isoformat() if getattr(item, "published_at", None) else None,
        "detected_at": item.detected_at.isoformat() if getattr(item, "detected_at", None) else None,
        "processing_status": _status_value(item.processing_status),
        "body_source": body_source_from_item(item),
        "fetch_ok": meta.get("fetch_ok") if isinstance(meta, dict) else None,
        **outcome.as_dict(),
    }


def pipeline_run_payload(run: Any, *, linked_event_ids: list[str] | None = None) -> dict[str, Any]:
    meta = _run_meta(run)
    detection = None
    if getattr(run, "stage", None) == DETECTION_STAGE:
        detection = outcome_from_detection_run(run, linked_event_ids=linked_event_ids).as_dict()
    event_id = getattr(run, "event_id", None)
    source_item_id = getattr(run, "source_item_id", None)
    return {
        "id": str(run.id),
        "stage": run.stage,
        "status": _status_value(run.status),
        "attempt": getattr(run, "attempt", None),
        "error_message": getattr(run, "error_message", None),
        "started_at": run.started_at.isoformat() if getattr(run, "started_at", None) else None,
        "finished_at": run.finished_at.isoformat() if getattr(run, "finished_at", None) else None,
        "event_id": str(event_id) if event_id is not None else None,
        "source_item_id": str(source_item_id) if source_item_id is not None else None,
        "trigger": meta.get("trigger") if isinstance(meta.get("trigger"), str) else None,
        "metadata_json": meta,
        "no_material_change": writing_no_material_change(run),
        "detection": detection,
    }


def summarize_detection_outcomes(outcomes: list[PublicationOutcome]) -> dict[str, Any]:
    by_family: dict[str, dict[str, Any]] = {}
    for row in outcomes:
        bucket = by_family.setdefault(row.outcome, {"count": 0, "codes": {}})
        bucket["count"] += 1
        codes = bucket["codes"]
        codes[row.code] = codes.get(row.code, 0) + 1
    return {
        family: {
            "count": data["count"],
            "outcome_label": OUTCOME_LABELS.get(family, family),
            "codes": [
                {"code": code, "count": count, "code_label": CODE_LABELS.get(code, code)}
                for code, count in sorted(data["codes"].items())
            ],
        }
        for family, data in by_family.items()
    }
