# Sin Línea

Medio informativo digital automatizado. El objeto central no es la “noticia”: es el **suceso** (`Event`). Varias publicaciones pueden ser evidencia del mismo hecho; el artículo público es la representación actual de lo que se sabe.

Este repositorio cubre la foundation, el dominio persistido, la ingesta RSS (M2), la detección conservadora de sucesos (M3) y la investigación dirigida de fuentes extra (M4). La UI pública entra más adelante.

## Arquitectura

Monolito modular + workers asíncronos:

- **web** — Next.js (App Router), Admin en `/admin`
- **api** — FastAPI
- **worker** — Celery (`ingestion`, `event_detection`, `research`)
- **beat** — Celery Beat (poll periódico de fuentes vigiladas)
- **postgres** — PostgreSQL + pgvector
- **redis** — broker/backend de Celery y health de Redis

## Cómo iniciar

1. Copiá las variables de entorno:

```bash
cp .env.example .env
```

Para el Admin local, `.env.example` ya trae `ADMIN_PASSWORD=dev-admin` y `APP_SECRET=dev-secret-change-me`. Las claves de IA (M3) no hacen falta para levantar el stack ni para el poll manual; sí hacen falta en el **worker** para extraer/vincular sucesos con modelos reales. Compose define `DATABASE_URL` y `REDIS_URL` hacia los servicios internos.

2. Levantá todo:

```bash
docker compose up --build
```

Servicios:

| Servicio | URL |
| --- | --- |
| Frontend | http://localhost:3000 |
| Admin | http://localhost:3000/admin |
| API | http://localhost:8000 |
| Health | http://localhost:8000/health |
| Postgres | localhost:5432 |
| Redis | localhost:6379 |

La API corre `alembic upgrade head` al arrancar. El frontend reescribe `/api/v1/*` hacia `API_URL` (same-origin: cookie `sl_admin`).

## Admin (M2 / M3 / M4)

Entrar en http://localhost:3000/admin con `ADMIN_PASSWORD`. Flujo operativo:

1. **Fuentes** — alta RSS (`feed_url`, `preferred_ingestion_method=RSS`)
2. Marcar **vigilada** (`is_monitored`)
3. **Poll** manual (encola `poll_source` en la cola `ingestion`)
4. El worker crea `SourceItem`s; la detección (`detect_event` en `event_detection`) abre o vincula un `Event`
5. Si el suceso es **nuevo**, se encola `research_event` en `research`. También se puede disparar a mano con **Investigar** en el detalle Admin.

M4 no es un crawler ni un radar de homepages: parte de un Event ya existente, arma pocas consultas con ventana temporal (`pd`/`pw`/`pm`/`py`), prefiltra por URL/dominio (máx. 3 hits por dominio) y solo descarga las URLs nuevas que Luna marca como el mismo suceso. Si el `SourceItem` ya existe en la base y no está ligado a ese Event, se reutiliza y se adjunta como `ADDITIONAL` sin volver a bajar la página. Un segundo clic mientras hay un `pipeline_run` `research` en `RUNNING` no dispara otra búsqueda (HTTP 409). `Event.status` no se degrada.

Caps: `MAX_RESEARCH_QUERIES_PER_EVENT` (4), `MAX_RESEARCH_RESULTS_PER_QUERY` (5), `MAX_RESEARCH_RESULTS_PER_DOMAIN` (3). Requiere `SEARCH_PROVIDER=brave` y `BRAVE_API_KEY` en el worker. Sin clave, el run queda `FAILED`.

El poll manual del Admin es el criterio de aceptación de M2. Beat es el periódico: cada `INGESTION_POLL_INTERVAL_SECONDS` (default **900**).

## Variables de entorno

Ver [`.env.example`](.env.example). Las claves y los IDs de modelo se configuran ahí; el dominio nunca hardcodea un vendor model ID.

M3 en el worker: `OPENAI_API_KEY`, `VOYAGE_API_KEY`, `LIGHT_PROCESSING_*`, `AMBIGUOUS_DEDUP_*`, `EMBEDDING_*`. M4 además: `BRAVE_API_KEY`, `SEARCH_PROVIDER`. Compose las pasa desde el `.env` del host.

## Migrations

Desde el contenedor de la API (ya ocurre al `up`):

```bash
docker compose exec api alembic upgrade head
docker compose exec api alembic current
```

Nunca uses `create_all()` como sistema de producción.

## Tests

Postgres y Redis deben estar arriba (el `docker compose up` alcanza; en este repo suelen correrse vía WSL).

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

Worker y Beat arrancan con Compose. El worker escucha `ingestion`, `event_detection`, `research` y `celery`.

```bash
docker compose exec api celery -A app.workers.celery_app inspect ping
```

Poll periódico (Beat): tarea `app.workers.tasks.poll_monitored_sources`, intervalo default 900s.

## Stack

- Frontend: Next.js, React, TypeScript, Tailwind CSS
- Backend: Python 3.12, FastAPI, SQLAlchemy 2, Pydantic, Alembic
- Jobs: Redis, Celery
- DB: PostgreSQL + pgvector
