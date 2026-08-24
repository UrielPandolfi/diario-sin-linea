# Sin Línea

Medio informativo digital automatizado. El objeto central no es la “noticia”: es el **suceso** (`Event`). Varias publicaciones pueden ser evidencia del mismo hecho; el artículo público es la representación actual de lo que se sabe.

Este repositorio cubre la **foundation** (infra local) y el **dominio** persistido. La ingesta RSS, la IA y la UI pública entran en milestones posteriores.

## Arquitectura

Monolito modular + workers asíncronos:

- **web** — Next.js (App Router)
- **api** — FastAPI
- **worker** — Celery
- **postgres** — PostgreSQL + pgvector
- **redis** — broker/backend de Celery y health de Redis

## Cómo iniciar

1. Copiá las variables de entorno:

```bash
cp .env.example .env
```

No hace falta llenar claves de IA para levantar M0/M1. Compose define `DATABASE_URL` y `REDIS_URL` hacia los servicios internos.

2. Levantá todo:

```bash
docker compose up --build
```

Servicios:

| Servicio | URL |
| --- | --- |
| Frontend | http://localhost:3000 |
| API | http://localhost:8000 |
| Health | http://localhost:8000/health |
| Postgres | localhost:5432 |
| Redis | localhost:6379 |

La API corre `alembic upgrade head` al arrancar.

## Variables de entorno

Ver [`.env.example`](.env.example). Las claves y los IDs de modelo se configuran ahí; el dominio nunca hardcodea un vendor model ID.

## Migrations

Desde el contenedor de la API (ya ocurre al `up`):

```bash
docker compose exec api alembic upgrade head
docker compose exec api alembic current
```

Nunca uses `create_all()` como sistema de producción.

## Tests

Postgres y Redis deben estar arriba (el `docker compose up` alcanza).

```bash
docker compose exec api pytest
```

Frontend:

```bash
docker compose exec web npm run lint
docker compose exec web npm run typecheck
```

O en el host, con Node 22+, dentro de `apps/web`: `npm install && npm run lint && npm run typecheck && npm run build`.

## Celery

El worker arranca con Compose. Tarea de comprobación:

```bash
docker compose exec api celery -A app.workers.celery_app inspect ping
```

## Fuentes (a partir de M2)

Todavía no hay Admin ni polling RSS. Las tablas `sources` / `source_items` ya existen. El alta de fuentes vigiladas y el poll manual llegan en el siguiente milestone.

## Stack

- Frontend: Next.js, React, TypeScript, Tailwind CSS
- Backend: Python 3.12, FastAPI, SQLAlchemy 2, Pydantic, Alembic
- Jobs: Redis, Celery
- DB: PostgreSQL + pgvector
