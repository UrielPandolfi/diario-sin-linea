# Índice de contexto

Mapa para localizar archivos. Ante conflicto con este índice o con `README.md`, gana el código. El README sirve para levantar el stack; no copiar su prosa de pipeline sin verificar.

Histórico (no cargar salvo que la tarea lo pida): `_master_prompt_extract.txt`, `.cursor/plans/`.

## Repositorio

| Ruta | Rol |
| --- | --- |
| `apps/web/` | Next.js 15 (App Router): UI pública + `/admin` |
| `apps/api/app/` | FastAPI, dominio, servicios, workers Celery |
| `apps/api/migrations/versions/` | Alembic (`0001` … `0014_llm_costs`) |
| `apps/api/tests/` | Pytest |
| `docker-compose.yml` | postgres, redis, api, worker, beat, web |
| `scripts/run_editorial_eval.py` | Eval editorial (fixtures; no RSS) |
| `.github/workflows/ci.yml` | pytest + lint/typecheck/build |

Entradas: [`apps/api/app/main.py`](../../apps/api/app/main.py), [`apps/api/app/workers/tasks.py`](../../apps/api/app/workers/tasks.py), [`apps/api/app/workers/celery_app.py`](../../apps/api/app/workers/celery_app.py), [`apps/web/middleware.ts`](../../apps/web/middleware.ts).

Routers (`main.py`): `api/health.py`, `api/public.py`, `api/cases.py`, `api/admin.py`, `api/admin_cases.py`. Prefijos: `/health`; público y casos en `/api/v1`; admin en `/api/v1/admin`.

## Si vas a trabajar en X

| X | Consultá |
| --- | --- |
| Pipeline Celery (etapas, enqueue) | `docs/ai/pipeline.md` + `workers/tasks.py` |
| Detección / create vs link / gate | `services/detection_service.py`, `editorial_gate.py`, `docs/ai/STATE.md` |
| Research, claims, verify, write, audit, publish | `services/{research,claim,verification,writing,audit,publish}_service.py` + `pipeline_lock.py` |
| Decisiones a preservar | `docs/ai/DECISIONS.md` (solo si hay evidencia de intención) |
| Estado, stubs, hallazgos | `docs/ai/STATE.md` |
| API pública / feed | `api/public.py`, `services/feed_ranking.py` |
| Admin pipeline | `api/admin.py`, `apps/web/app/admin/` (Publicaciones `/admin/publications`, costos en tablero y suceso) |
| Casos de lectores / contacto | `api/cases.py`, `admin_cases.py`, `services/case_service.py`, `case_rate_limit.py`; UI `/contacto`, `/seguimiento/[token]`, `/admin/cases` |
| Revisión editorial | `services/editorial_service.py`, `features/admin/editorial-revise-form.tsx` |
| Config / providers | `core/config.py`, `.env.example`, `providers/registry.py` |
| Modelos | `models/` (`event`, `source`, `claim`, `article`, `pipeline`, `reader_case`, `llm_usage`, `llm_price`) |
| Continuidad entre chats | `docs/ai/HANDOFF.md` |

Web pública: `apps/web/app/(public)/` (`/`, `/buscar`, `/local`, `/en-vivo`, `/noticias/[slug]`, `/contacto`, `/seguimiento/[token]`, `/perfil`). Stubs: `/seguidos`, `/notificaciones`, `/guardados`. Localidad: `/entrar`, `/onboarding`. Cliente: `apps/web/lib/api/`, `features/`.

`/como-funciona` queda fuera de `(public)`: es una landing con chrome propio (`features/how-it-works/`), sin el `AppShell` ni la barra lateral.

## Validación (comandos en CI / README)

Backend (Postgres + Redis; Compose o job CI):

```bash
docker compose exec api alembic upgrade head
docker compose exec api pytest
```

Frontend (`apps/web` o `docker compose exec web`): `npm run lint`, `npm run typecheck`, `npm run build`.

Eval opcional: `docker compose exec api python scripts/run_editorial_eval.py --mode full-editorial`.

Ampliá el subset de pytest al módulo tocado (`apps/api/tests/test_*.py`).
