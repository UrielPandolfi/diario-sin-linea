# Sin Línea

Medio informativo digital automatizado. El objeto central no es la “noticia”: es el **suceso** (`Event`). Varias publicaciones pueden ser evidencia del mismo hecho; el artículo público es la representación actual de lo que se sabe.

Este repositorio cubre la foundation, el dominio persistido, la ingesta RSS (M2), la detección conservadora de sucesos (M3), la investigación dirigida de fuentes extra (M4), la extracción/resolución barata de claims (M5), la verificación cara de Sol (M6), la redacción de un article draft (M7), la auditoría Sol → rewrite (M8) y la publicación autónoma más API pública (M9). La UI pública de producto entra en M10.

## Arquitectura

Monolito modular + workers asíncronos:

- **web** — Next.js (App Router), Admin en `/admin`
- **api** — FastAPI
- **worker** — Celery (`ingestion`, `event_detection`, `research`, `claim_resolution`, `verification`, `writing`, `auditing`, `publishing`)
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

## Admin (M2 / M3 / M4 / M5 / M6 / M7 / M8 / M9)

Entrar en http://localhost:3000/admin con `ADMIN_PASSWORD`. Flujo operativo:

1. **Fuentes** — alta RSS (`feed_url`, `preferred_ingestion_method=RSS`)
2. Marcar **vigilada** (`is_monitored`)
3. **Poll** manual (encola `poll_source` en la cola `ingestion`)
4. El worker crea `SourceItem`s; la detección (`detect_event` en `event_detection`) abre o vincula un `Event`
5. Si el suceso es **nuevo**, se encola `research_event` en `research`. También se puede disparar a mano con **Investigar** en el detalle Admin.
6. Si research no quedó `skipped`, se encola `resolve_event_claims` en `claim_resolution` (extracción Luna + resolución DeepSeek). También se puede disparar a mano con **Resolver claims**.
7. Si claims no quedó `skipped`, se encola `verify_event_claims` en `verification` (Brave por claim + Sol). También se puede disparar a mano con **Verificar**. Si la policy no selecciona nada, el run termina `SUCCESS` sin Brave ni Sol.
8. Si verification quedó `SUCCESS` (no `FAILED` ni `skipped`), se encola `write_event_article` en `writing`. También se puede disparar a mano con **Redactar**. Un segundo clic con `writing`, `auditing` o `publishing` en `RUNNING` responde HTTP 409 (un solo índice parcial cubre los tres stages).
9. Si writing quedó `written=True`, se encola `audit_event_article` en `auditing`. También se puede disparar a mano con **Auditar**. Sol revisa el draft; si falla, Claude reescribe hasta `MAX_AUDIT_REWRITE_CYCLES` (default 2) y Sol vuelve a auditar. Si `passed=true`, el worker encola `publish_event_article` (sin gate `AUTO_PUBLISH`). Si el cap se agota con `passed=false`, el `Article` sigue `DRAFT` y **no** se publica. `READY_FOR_REVIEW` no se usa como cola humana. `Event.status` pasa a `PUBLISHED` solo en publish.
10. Un artículo publicado aparece en `GET /api/v1/feed`, `/live`, `/now`, `/local?locality=`, `/nearby`, `/search` y `/articles/{slug|public_id}`. Un update material reescribe un working copy `DRAFT` sin sacar el live (`published_version` anterior) hasta que Sol vuelva a aprobar.

M4 no es un crawler ni un radar de homepages: parte de un Event ya existente, arma pocas consultas con ventana temporal (`pd`/`pw`/`pm`/`py`), prefiltra por URL/dominio (máx. 3 hits por dominio) y solo descarga las URLs nuevas que Luna marca como el mismo suceso. Si el `SourceItem` ya existe en la base y no está ligado a ese Event, se reutiliza y se adjunta como `ADDITIONAL` sin volver a bajar la página. Un segundo clic mientras hay un `pipeline_run` `research` en `RUNNING` no dispara otra búsqueda (HTTP 409). `Event.status` no se degrada.

M5 extrae afirmaciones no triviales de los snippets (no páginas completas), valida que el excerpt exista en el `SourceItem`, fusiona por `assertion_key` y agrupa competidores por `comparison_key`. `SUPPORTED` exige SUPPORTS de al menos dos medios independientes (dominio distinto). Varias notas del mismo medio quedan `SINGLE_SOURCE`. `SUPPORTS`/`CONTRADICTS` viven en `ClaimEvidence`; M5 no reclasifica `EventSource.relation_type` ni llama a Sol/Brave. Caps de snippet: 1500 caracteres. Un segundo clic con `claim_resolution` en `RUNNING` responde HTTP 409.

M6 no re-investiga el suceso: una policy determinista elige hasta 5 claims (flag M5, `declaracion`, cifras/documentos HIGH inciertos, o HIGH + `SINGLE_SOURCE`). Vetos: `OUTDATED`/`DISPROVEN` y hechos/estados mundanos ya cubiertos. Brave busca el texto del claim (no el título del Event). Sol prioriza evidencia primaria; la ausencia de primaria no fuerza `UNCERTAIN` si hay medios independientes consistentes. `Event.status` y los `relation_type` previos no se tocan; solo las URLs que Sol cita se adjuntan como `ADDITIONAL`. Un segundo clic con `verification` en `RUNNING` responde HTTP 409.

M7 arma un `ArticleContext` (claims, fuentes, verificación compacta; sin HTML crudo ni el Event entero) y pide a Claude JSON (`headline`, `summary`, `body`) vía `generate_structured`. `WRITING_PROVIDER=anthropic` parsea JSON (no structured nativo). Persistencia: un `Article` por `event_id`. Un segundo write sin cambio material no crea `ArticleVersion`. Un `PUBLISHED` con cambio material vuelve a `DRAFT` como working copy; el live público sigue en `published_version`. `Event.status` no se toca en writing.

M8 audita ese draft con Sol (`AUDITING_PROVIDER` OpenAI o DeepSeek; Anthropic no es auditor). Issues viven en `pipeline_runs.metadata_json` del stage `auditing` (no en `Correction`). Writing, auditing y publishing no corren a la vez sobre el mismo Event (pre-check + un índice único parcial compartido). Cada rewrite persistido es una `ArticleVersion` (`change_reason=audit_rewrite`) antes del siguiente Sol; si Sol falla después, el run queda `FAILED` y el Article sigue `DRAFT` en esa versión para reintentar con **Auditar**. M8 no setea `READY_FOR_REVIEW`.

M9 publica solo si el último audit `SUCCESS` tiene `passed=true` sobre `current_version`. `AUTO_PUBLISH` en `.env.example` no es gate. `POST /api/v1/admin/events/{id}/publish` es retry ops (202 / 200 already_published / 409 `audit_not_passed`). No hay rechazo editorial. `scope=local` filtra en estricto por localidad.

Caps: `INITIAL_RESEARCH_QUERIES` (2) y `MAX_RESEARCH_QUERIES_PER_EVENT` (4, solo si hay escalación). `MAX_STANDARD_EVENT_SOURCES` (4) / `MAX_ESCALATED_EVENT_SOURCES` (8) limitan INITIAL+ADDITIONAL. `MAX_RESEARCH_RESULTS_PER_QUERY` (5), `MAX_RESEARCH_RESULTS_PER_DOMAIN` (3). M6: `MAX_VERIFICATION_CLAIMS_PER_EVENT` (5), `MAX_VERIFICATION_QUERIES_PER_CLAIM` (2), `MAX_VERIFICATION_RESULTS_PER_QUERY` (3). M7: `MAX_WRITING_CLAIMS_PER_EVENT` (40, solo el prompt a Claude; el detector de cambio material ve todos los claims), `MAX_WRITING_SOURCES_PER_EVENT` (20). M8: `MAX_AUDIT_REWRITE_CYCLES` (2). Búsqueda: `SEARCH_PROVIDER=exa` o `brave` más `EXA_API_KEY` / `BRAVE_API_KEY` en el worker. Sin clave del provider elegido, research/verification quedan `FAILED` y verification **no** encola writing.

El poll manual del Admin es el criterio de aceptación de M2. Beat es el periódico: cada `INGESTION_POLL_INTERVAL_SECONDS` (default **900**). Para testeo acotado: `MAX_NEW_EVENTS_PER_POLL=3` (default `0` = sin tope) limita cuántos sucesos **nuevos** de un mismo Poll encolan research→publish; **Investigar** a mano no usa ese tope.

## Variables de entorno

Ver [`.env.example`](.env.example). Las claves y los IDs de modelo se configuran ahí; el dominio nunca hardcodea un vendor model ID.

M3 en el worker: `OPENAI_API_KEY`, `VOYAGE_API_KEY`, `ULTRA_LIGHT_PROCESSING_*` (extracción inicial; Luna/`LIGHT_PROCESSING_*` es fallback), `AMBIGUOUS_DEDUP_*`, `EMBEDDING_*`. El gate editorial descarta `SPORTS_ONLY`/`IRRELEVANT` y todo lo que no sea Rosario (Santa Fe, AR) **antes** de embeddings. M4/M6 búsqueda: `SEARCH_PROVIDER` (`exa` o `brave`), `EXA_API_KEY` y/o `BRAVE_API_KEY`. M5: `DEEPSEEK_API_KEY`, `CLAIM_RESOLUTION_*` (flash) y `CLAIM_RESOLUTION_ESCALATED_*`. M6: `VERIFICATION_PROVIDER`, `VERIFICATION_MODEL` (OpenAI o DeepSeek; no hardcodea model IDs). M7: `ANTHROPIC_API_KEY`, `WRITING_PROVIDER`, `WRITING_MODEL` (sin hardcodear model IDs). M8: `AUDITING_PROVIDER`, `AUDITING_MODEL` (OpenAI o DeepSeek; sin hardcodear model IDs). M9 no agrega providers. Compose pasa `FEED_*` y `NEARBY_WINDOW_HOURS`.

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

Worker y Beat arrancan con Compose. El worker escucha `ingestion`, `event_detection`, `research`, `claim_resolution`, `verification`, `writing`, `auditing`, `publishing` y `celery`.

```bash
docker compose exec api celery -A app.workers.celery_app inspect ping
```

Poll periódico (Beat): tarea `app.workers.tasks.poll_monitored_sources`, intervalo default 900s.

## Stack

- Frontend: Next.js, React, TypeScript, Tailwind CSS
- Backend: Python 3.12, FastAPI, SQLAlchemy 2, Pydantic, Alembic
- Jobs: Redis, Celery
- DB: PostgreSQL + pgvector
