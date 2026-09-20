# Handoff

**Fecha:** 2026-09-20

**Tarea:** Revisión integrada Track C C1–C8. C9 no empezó.

## Qué quedó

C1–C8 están en código en `track-c`. La revisión conjunta confirmó los contratos y un fallo C3+C6: `editorial_scopes` sellaba `verified_scope` con el texto entero si el status era `SINGLE_SOURCE`/`SUPPORTED`, aunque el único SUPPORTS del assessment hubiera sido rechazado. Ahora el texto entero exige `SUPPORTS` persistido; sin él ambos scopes quedan `None`. QUALIFIES con fragmento no cambia. El GET de V1 sigue congelado al snapshot; un split posterior no altera la tarjeta publicada.

## Validación

- Dirigidos (corrección): `test_editorial_reason.py`, `test_verification.py` (rechazo / DNE / SUPPORTS mixto), `test_proposition_comparison.py` (C7), `test_compound_act_characterization.py::test_c2_new_extraction_does_not_change_frozen_v1` — 27 passed
- Subset C1–C8 tocado: 170 passed
- Suite API completa: **744 passed**, 1 warning Alembic preexistente
- `python -m pytest -q` en `apps/api`

## Pendiente

C9 (copy). Relativos/gerundios y atributos vagos no se atomizan. Claims históricos mixtos no se migran. QUALIFIES sigue sin `unsupported_scope` por resta. `pending`/`failed` no se escriben en SUCCESS. Sin migración ni backfill.
