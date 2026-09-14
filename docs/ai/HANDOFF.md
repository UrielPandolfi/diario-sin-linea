# Handoff

Reemplazar este archivo al cerrar una tarea o al continuar en otro chat. No es un diario de sesiones.

**Fecha:** 2026-09-13  
**Tarea:** Writing/Audit no pueden convertir un `SINGLE_SOURCE` bien calculado en un hecho categórico. Verification no se tocó.

## Objetivo de este chat

Titular, bajada y lead deben conservar el posture. Combinar dos `SINGLE_SOURCE` no eleva certeza. El dato se atribuye, no se borra.

## Avances

- Prompts de writing/audit: atribución en superficie, regla de composición, elevación semántica (militante ≠ dirigente).
- Payload de Audit incluye `lead`; el titular se juzga por sí mismo.
- Tipos existentes: `UNSUPPORTED_CLAIM` / `ATTRIBUTION` / `INFERENCE`.
- Tests A–G en `test_writing_certainty.py`.

## Limitaciones

Sol sigue siendo un LLM: los tests clavan contrato, payload y bloqueo HIGH, no un validador semántico determinista. No se regeneró la nota viva de San José 1111.

## Pendientes

Track B. Eval paga. Hover/copy de tarjetas (fuera de esta corrección). Reescribir la nota real de San José 1111 con writing+audit reales.

## Archivos relevantes

`prompts/article_writing.md`, `prompts/article_audit.md`, `services/writing_service.py`, `services/audit_service.py`, `tests/test_writing_certainty.py`, `docs/ai/DECISIONS.md`, `docs/ai/STATE.md`.

## Pruebas

Desde `apps/api` (Postgres+Redis):

```
python -m pytest tests/test_writing_certainty.py tests/test_writing.py tests/test_audit.py tests/test_audit_policy.py tests/test_evidence_posture.py -q --tb=short
python -m pytest -q --tb=line
```

## Siguiente paso

No mezclar con el popover. Si se republica San José 1111, el titular debe atribuir; no eliminar Recalde/Calle del artículo.
