# Handoff

**Fecha:** 2026-09-20

**Tarea:** Track C — PR C6 (admisión semántica del assessment y suficiencia del respaldo). C7 no empezó.

## Qué quedó

`assessment_has_support` solo cuenta `SUPPORTS` admitidos por `_admit_relation`. El juicio crudo del modelo no promociona status ni evita Sol. `DOES_NOT_ESTABLISH` queda en `assessments[]` y `comparison_checks`, sin `ClaimEvidence` ni `EventSource`. Un assessment válido sin apoyo es `complete`; `None` escala a Sol. No se tocaron prompts. Un `UNCERTAIN` con SUPPORTS crudo rechazado ahora usa el Sol que ya existía.

## Validación

- Dirigidos: `test_verification_plan.py`, `test_proposition_comparison.py`, `test_verification.py`, `test_editorial_evidence.py`, `test_independent_reporting.py` — **134 passed**
- Suite API completa: **709 passed**, 1 warning Alembic preexistente
- `python -m pytest -q` en `apps/api`

## Pendiente

C7. PR separado de prompt de assessment si el modelo etiqueta mal la relación. No hay migración ni backfill.
