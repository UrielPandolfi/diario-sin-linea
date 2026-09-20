# Handoff

**Fecha:** 2026-09-20

**Tarea:** Track C — PR C5 (validador de superficie y coverage del titular). C6 no empezó.

## Qué quedó

Audit valida de forma determinista titular, bajada y lead contra `public_rendering` del snapshot de **esa** versión. Incumplimientos HIGH producen `structural_block` (sin rewrite, sin LLM extra, sin auto-publish). El núcleo del titular debe equivaler a un claim material. Matching conservador: EQUIVALENT valida; PARTIAL/mención = indeterminado LOW. Legacy/incompleto no se inventa ni cae a Verification live. C4 no se reescribió para hacer pasar tests.

## Validación

- Dirigidos C5 (`test_surface_validation.py` + writing/audit/publish/Track B tocados): incluidos en la suite
- Suite API completa: **697 passed**, 1 warning Alembic preexistente
- `docker compose exec api pytest -q` no se ejecutó: se usó `python -m pytest -q` en `apps/api`

## Pendiente

C6. No hay migración. No backfill de ArticleVersion.
