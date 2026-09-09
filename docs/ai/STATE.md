# Estado

Revisión: 2026-09-08. Track A (observabilidad y costos Admin) está en código. Track B **no** se implementó ni se da por resuelto. Etapa 1 de claims/evidencia/verificación (`editorial-evidence-1`) está en código y tests con dobles; etapa 2 (auditor, UI, bloqueo de publish) **no**.

Separar: **en código** ≠ **cubierto por tests** ≠ **verificado en esta sesión**.

## En código y cableado

Pipeline Celery: poll → detect → research → claims → verify → write → audit → publish (`workers/tasks.py`). Admin puede re-disparar stages. API pública: feed, live, now, local, nearby, search, artículo por slug/`public_id` (`api/public.py`).

Ingesta RSS (HTML no soportado en `ingestion_service.py`). Gate editorial en detección (`editorial_gate.py`). Un `Article` por evento; versiones; `editorial_hold` bloquea el enqueue autónomo de publish.

Admin Track A: `/admin/publications` (estado actual vs ejecuciones de período), costos estimados con libro/snapshot (`0014_llm_costs`), procedencia de cuerpo (`body_source`), skip de cuota persistido, fallo histórico ≠ fallo abierto. Atribución 1:1 de `LlmUsage`; backfill de embeddings separado.

Casos de lectores y revisión editorial: routers en `main.py`, migración `0013_reader_cases`, UI `/contacto`, `/seguimiento/[token]`, `/admin/cases`. **No** pasan por Celery.

## Tests que existen (no = pasados ahora)

Backend: además de la suite previa, `test_editorial_evidence`, `test_publication_outcome`, `test_admin_publications`, `test_llm_costs`. Frontend: lint/typecheck/build en CI; **no** hay tests unitarios web.

## Hallazgos de cableado (no decisiones)

1. **Link no encola research.** `detect_event` solo llama `research_event` si `created` y hay `event_id`. Vincular o filtrar no reabre research→publish. **Track B:** no verificado ni reparado en A.
2. **`AUTO_PUBLISH` no se lee** fuera de Settings. El path vivo publica por audit `passed` + no hold.
3. **`READY_FOR_REVIEW` no se asigna** en servicios.

## Track B — no resuelto al cerrar A

No se escribieron tests de `embedding_high`, Terra ni `level1_code` positivo. No se reabre research al linkear. El hueco `no_claims` (write saltea sin evaluar novedad) y los cambios factuales sin claims **siguen**. No hay `unique(source_item_id)` en `event_sources` (una publicación puede ser varios sucesos). La carrera de dos `detect` concurrentes no se evaluó. Research que adjunta ítems no los marca PROCESSED.

Hasta B, “fuente agregada” >> “actualización publicada” es el cableado real. Dedup por embeddings/Voyage **no** quedó verificado en esta tarea.

## Claims / verify — etapa 1 en código; etapa 2 no

En código: contrato versionado en `metadata_json`, par claim↔verify, coverage/recovery, split de compuestos, packet claim-primero, independencia por `information_origin`, primaria auténtica de utterance. Tests de política con dobles (Alberto/Bregman, dos URLs misma fuente, par desparejado). **No** demuestran que Luna/Sol reales dejen de confundir proposiciones; eval con modelos reales queda fuera (`scripts/run_editorial_eval.py`).

Etapa 2 (siguiente, **no** implementada): issues de auditor sobre el snapshot del par; Admin UI de `support_basis` / coverage; **bloqueo** de publish (o de afirmar el título) si `coverage_gap` o `verification_incomplete`. El recordatorio Writing no es ese gate. RELATED_CONTEXT sigue sin adjuntarse en research. Corridas históricas sin fingerprint se tratan como `unknown`.

## Parcial / stub / posible defecto

- UI “Próximamente”: `/seguidos`, `/notificaciones`, `/guardados`; mapa en local/home; login social en `/entrar`; cuentas en perfil.
- `editorial_hold` se pone `True` en revise UPDATE/CORRECTION; el override de publish no lo pone en `False`.
- Helpers Rosario / `OUTSIDE_TARGET_LOCALITY` en el gate **no** se usan en `evaluate_editorial_gate`.
- Filas `LlmUsage` anteriores a A2: USD unknown; atribución inferida de FKs; backfill vs query de embeddings no se parte.
- `body_source` histórico sin metadata = `unknown`. Quota skip anterior a A1 no reconstruible.

README desactualizado en: “solo Rosario”, proveedores de writing/audit fijos a Claude, `MAX_VERIFICATION_QUERIES_PER_CLAIM` (código/example = 3).
