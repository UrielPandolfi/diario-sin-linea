# Handoff

**Fecha:** 2026-09-20

**Tarea:** Track C — PR C4 (`public_rendering`). C5 no empezó.

## Qué quedó

Cada decisión completa persiste un contrato `PublicRendering` (permisos de atribución, categórico, titular sin atribuir, lenguaje de corroboración independiente). Se deriva en código de status + evaluation_state + support_basis + rol + reason/scopes. Skipped/legacy: `None`. El GET de V1 lee el snapshot de V1; publicar V2 muestra el de V2. Writing no recibe el contrato. C3 quedó en `3523551`.

## Validación

- Dirigidos C4 (`test_public_rendering.py` + C1–C3 relacionados): **120 passed**
- Suite API completa: **679 passed**, 1 warning Alembic preexistente
- `docker compose exec api pytest -q` no se ejecutó: `docker` no está en PATH; se usó `python -m pytest -q` en `apps/api`

## Pendiente

C5 (validador de superficie). No hay migración. No backfill de ArticleVersion.
