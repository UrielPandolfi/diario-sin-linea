# Handoff

**Fecha:** 2026-09-20

**Tarea:** Track C — PR C3 (`reason_code` + scopes deterministas). C4 no empezó.

## Qué quedó

La resolución estructurada de un claim con `evaluation_state=complete` tiene `reason_code` determinista, `final_reason` renderizado desde ese código, y `verified_scope` solo cuando un `claim_fragment` de QUALIFIES identifica un subconjunto propio del texto evaluado. No hay split C8 del resto. Skipped/legacy no reciben esas razones. Independencia, umbrales de contradicción, Writing y C1/C2 se conservan.

## Validación

- Dirigidos C3: **103 passed**
- Suite API completa: **671 passed**, 1 warning Alembic preexistente
- `docker compose exec api pytest -q` no se ejecutó: `docker` no está en PATH; se usó `python -m pytest -q` en `apps/api`

## Pendiente

C4 y el resto de Track C. No hay migración. No backfill de ArticleVersion.
