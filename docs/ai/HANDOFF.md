# Handoff

**Fecha:** 2026-09-24

**Tarea:** PublishService usa la misma normalización de Audit para la omisión de titular. Sin commit ni publicación operativa.

## Resultado

`_audit_passed_for_current` sigue exigiendo Audit `passed` de esa versión y un snapshot atado. Los estructurales se revalidan con `normalized_structural_issues`. La omisión tolerada del titular no vuelve a bloquear. Integridad, cobertura y correspondencia sí.

## Pendiente

Recorrido `DISPROVEN` hasta Writing y el frontend. Formosa en conjunto, cobertura Esteche/Interpol, contratos equivalentes de Rafecas, selección de Verification y duplicados de sucesos quedan fuera.

## Validación

Prueba de integración en Postgres descartable: Florencio Varela V1, un caso sintético equivalente, y los negativos de excepción e integridad.
