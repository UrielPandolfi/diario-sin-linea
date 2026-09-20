# Handoff

**Fecha:** 2026-09-20

**Tarea:** TRACK C PR C10 — UI de respaldo (popover accesible y panel inferior móvil).

## Qué quedó

C10 está en código sobre C9 (`ee56641`). Escritorio abre un popover (hover fino + ancho ≥768); el resto usa un bottom sheet modal. Desktop y móvil comparten `ClaimEvidenceList` y el copy público C9. No hay inferencia editorial en frontend ni llamadas al abrir. C11 no empezó.

## Pendiente

C11 (export/consulta). Relativos/gerundios y atributos vagos no se atomizan. Claims históricos mixtos no se migran. QUALIFIES sigue sin `unsupported_scope` por resta. `pending`/`failed` no se escriben en SUCCESS.
