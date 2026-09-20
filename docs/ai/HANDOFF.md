# Handoff

**Fecha:** 2026-09-20

**Tarea:** TRACK C PR C9 — contrato público de copy basado en la evidencia.

## Qué quedó

C9 está en código sobre `8dfc167`. El renderer de `claim_card_presentation` proyecta copy determinista desde el snapshot de la versión. El GET público ya no expone `demotion`. Admin conserva el campo interno. El consumidor web lee los textos del backend. Writing no recibe el copy público. C10/C11 no empezaron.

## Pendiente

C10 (popover/disclosure) y C11 (export/consulta). Relativos/gerundios y atributos vagos no se atomizan. Claims históricos mixtos no se migran. QUALIFIES sigue sin `unsupported_scope` por resta. `pending`/`failed` no se escriben en SUCCESS.
