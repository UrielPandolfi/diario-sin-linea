# Handoff

**Fecha:** 2026-09-21

**Tarea:** Restaurar `test_published_update_keeps_live_until_passed_audit` frente a C5, sin debilitar el contrato.

## Resultado

El fallo no era un bug de Audit/C5. Tras el update material, Writing emitía V2 con titular `Nuevo titular con heridos` y snapshot del par viejo (solo el claim del choque). C5 marcaba HIGH `headline_uncovered` y `structural_block` en el primer audit (`audit_count=1`), antes del tope de rewrites.

El fixture ahora persiste un par claim↔verify del set nuevo y redacta/reescribe titulares equivalentes al claim de heridos, con `public_rendering` completo. Se conservan las aserciones de que la versión publicada no cambia hasta Audit passed + publish.

Worker y Beat siguen detenidos. No se reingirió ni se tocó `sin_linea`.

## Pendiente

- Recuperar el contenido editorial local (sin backup utilizable).
- No arrancar worker/Beat ni polling hasta esa recuperación.
