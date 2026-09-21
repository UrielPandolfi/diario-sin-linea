# Handoff

**Fecha:** 2026-09-21

**Tarea:** Cierre acotado post-C11 — tope 50 del freeze público y visual Admin de trazabilidad.

## Qué quedó

C11 sigue en `b325852`. El GET público ya no congela claims con `list_for_event(limit=50)`. `_frozen_public_claims` llama `list_snapshot_binding_runs` (writing/auditing atados a esa versión, sin cap de recencia) y el mismo `evidence_snapshot_for_version`. La ventana de 50 sí desplazaba el writing de V1; el GET perdía el snapshot y caía al fallback neutral. No se eligió otra corrida por fecha ni fingerprint.

Panel Admin «Trazabilidad de versión» comprobado en Next local `:3001` contra API con el código actual (`AUTO_PUBLISH=false`, worker/beat apagados, `auto_poll_enabled=false`). Selector publicada vs current, JSON de la selección, borrador sin publicada (409 en `/trace`, no sustituye live) y `verification_run_id` ausente sin rellenar.

## Pendiente

Revisión de merge. No merge. No deploy. Limitaciones ya aceptadas: relativos/gerundios; mixtos históricos; QUALIFIES; `pending`/`failed` no se escriben en SUCCESS; visual C10 solo en chat. Overlay Next «1 Issue» es de automatización Cursor, no de la app. `list_for_event(limit=50)` permanece en el historial Admin de corridas, fuera de este freeze.
