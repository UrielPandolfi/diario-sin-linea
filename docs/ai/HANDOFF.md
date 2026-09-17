# Handoff

Reemplazar este archivo al cerrar una tarea o al continuar en otro chat. No es un diario de sesiones.

**Fecha:** 2026-09-17

**Tarea:** Normalizar `DATABASE_URL` a `postgresql+psycopg://` para Railway. Cerrado.

## Qué quedó

El runtime usa `psycopg[binary]` v3, no psycopg2. Compose/CI ya mandan `postgresql+psycopg://`. Railway inyecta `postgresql://` y SQLAlchemy carga `postgresql.psycopg2`. `Settings` reescribe `postgres://` y `postgresql://` a `postgresql+psycopg://`.

## Validación

- `pytest tests/test_database_url.py tests/test_health.py`: 5 passed.
- `python -m alembic upgrade head` con `DATABASE_URL=postgresql://sin_linea:sin_linea@postgres:5432/sin_linea`: exit 0 (sin `psycopg2`).

## Pendiente

Worker y beat en Railway (mismo Dockerfile, start Celery). `API_URL` en Vercel cuando la API tenga URL pública.
