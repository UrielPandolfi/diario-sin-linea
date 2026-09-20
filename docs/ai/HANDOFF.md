# Handoff

**Fecha:** 2026-09-20

**Tarea:** TRACK C PR C11 — trazabilidad por versión en Admin/export y cierre del track.

## Qué quedó

C11 está en código sobre C10 (`27692c1`). C2 ya ataba el snapshot a la versión; C11 expone esa cadena en Admin/export y sella `writing_run_id` al persistir Writing (fuera del prompt). Default: `published_version`. Selección explícita de borrador/histórica. Sin publicada: 409, no se presenta el borrador como live. Sin migración.

Consulta: `GET /api/v1/admin/articles/{id}/trace` y `GET /api/v1/admin/articles/{id}/versions/{n}/trace`. Sección en `/admin/events/[id]`. Schema de export `article-version-trace-1` ≠ `contract_version` del snapshot.

C11 cerrado. Track C no está “completo para merge/despliegue”: siguen los pendientes de C8–C10 (relativos/gerundios, mixtos históricos, QUALIFIES, `pending`/`failed`, visual de C10 solo en chat).

## Pendiente

No merge. No deploy. Verificación visual de C10 no versionada. Freeze público de claims sigue con `list_for_event(limit=50)`; el export C11 usa `list_lineage_runs` sin ese tope.
