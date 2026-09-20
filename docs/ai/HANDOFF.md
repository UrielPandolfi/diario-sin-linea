# Handoff

**Fecha:** 2026-09-20

**Tarea:** Track C — PR C7 (CONFLICTING solo entre proposiciones comparables). C8 no empezó.

## Qué quedó

`CONFLICTING` solo se fija entre proposiciones comparables. `_reconcile_competing_values` y `_reconcile_verified_competitors` (y las rutas `SUPPORTS`+`CONTRADICTS` / status propuesto) reutilizan `conflict_comparability`. Un utterance no se refuta con el contenido declarado. Descartar un par no promueve `SUPPORTED`. `DISPROVEN` y la admisión C6 se conservan. Sin cambios de prompt ni llamadas LLM nuevas.

## Validación

- Dirigidos: `test_claims.py`, `test_proposition_comparison.py`, `test_verification.py`, `test_track_b.py` — cubiertos en la suite
- Suite API completa: **725 passed**, 1 warning Alembic preexistente
- `python -m pytest -q` en `apps/api`

## Pendiente

C8. Si el extractor no trae período/unidad/ámbito, el par queda inconcluso; no se infiere. PR separado de prompt de assessment (C6) si el modelo etiqueta mal la relación. No hay migración ni backfill.
