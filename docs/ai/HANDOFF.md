# Handoff

**Fecha:** 2026-09-16

**Tarea:** implementar Track B del MVP (EXISTING_EVENT → evidencia incremental → materialidad editorial → Writing desde live → Audit → READY_FOR_REVIEW, V1 live, publish manual).

## Resultado

Track B quedó cableado sobre servicios/tablas existentes. No hubo microservicios, tablas de snapshots nuevas, cambios de umbrales 0.72/0.88, Voyage/Terra, ni auto-publish de actualizaciones.

## Implementación vigente

- `detect_event`: create → research; link nuevo → `resolve_event_claims(event_id, existing_event, source_item_id)`; `already_linked` no reabre.
- Claims incremental: extrae solo la SourceItem nueva, merge `assertion_key`, re-resuelve tocados + hermanos `comparison_key`.
- Material editorial: `status_confirmed` / `evidence_posture_changed` no reescriben; conflicto, valor, HIGH/MEDIUM nuevo, corrección, DISPROVEN/OUTDATED sí.
- Writing update: `published_version` live + `knowledge_delta` + claims autoritativos, sin `source_contexts`. Retry `unaudited_candidate` reencola Audit sin V3.
- Audit passed con live: `Article.status=READY_FOR_REVIEW`, Event sigue PUBLISHED, sin enqueue de publish.
- API pública: claims del live congelados al snapshot de esa versión.

## Validación

Suite completa (código montado sobre Postgres/Redis de Compose):

```text
568 passed, 2 warnings in 199.18s
```

Warnings preexistentes: Starlette `BlockingPortal` y Alembic `path_separator`.

Focalizado Track B + Detection/Claims/Writing/Audit/Publishing/Research/budget/posture/labels/verification: **211 passed**.

## Alcance y pendientes

Pendientes reales de este MVP: eval con modelos reales; no se agregó `unique(source_item_id)` en `event_sources`; no se evaluó la carrera de dos `detect` concurrentes. Dedup/Voyage reales siguen fuera.
