# Handoff

Reemplazar este archivo al cerrar una tarea o al continuar en otro chat. No es un diario de sesiones.

**Fecha:** 2026-09-08  
**Tarea:** Track A — control operativo y costos (Admin). Track B no implementado.

## Objetivo de este chat

Observabilidad de publicaciones y costos estimados sobre `pipeline_runs`, `SourceItem` y `llm_usages`, con atribución 1:1 y snapshot de tarifas. Sin cambiar gates, prompts ni políticas de retry. Sin reparar el circuito de actualización al vincular.

## Avances

- Mapper de estado actual vs corridas de período (`publication_outcome.py`); listado Admin `/admin/publications` + historial por ítem.
- Procedencia de cuerpo (`body_source`) en ingest RSS / research / verify; no se usa `has_extracted_body` como “leída”.
- Skip de cuota persistido como `PipelineRun` de detección.
- Uso LLM: caché, modelo pedido/reportado, fallos sin tokens, intento BadRequest interno, sello `event_id` solo si `created`, backfill de embeddings separado.
- Libro `llm_price_books` / `llm_price_rates` (migración `0014`) + `rate_snapshot` por llamada. Semilla: gpt-4o, gpt-4o-mini, gpt-5-nano, gpt-5.6-luna, voyage-3.
- Stats/costos: unique vs attempts, subtotal conocido + cobertura, fallos abiertos ≠ último error histórico.
- `no_material_change` solo a nivel Event/write.

## Pendientes

Track B (siguiente trabajo, **no** resuelto): verificar embeddings/Terra/`level1_code`; reabrir research al linkear (si se decide); novedad con 0 claims o sin claims nuevos; carrera de detección; no imponer `unique(source_item_id)`. Ver `docs/ai/STATE.md`.

Aplicar `alembic upgrade head` (0014) en cada entorno. Estimación ≠ factura.

## Archivos relevantes

`apps/api/app/api/admin.py`, `services/publication_outcome.py`, `services/cost_service.py`, `services/usage_recorder.py`, `migrations/versions/0014_llm_costs.py`, `apps/web/app/admin/publications/`, `docs/ai/STATE.md`, `docs/ai/pipeline.md`.

## Pruebas

- `pytest` (API en Compose): `test_publication_outcome`, `test_admin_publications`, `test_llm_costs`, `test_llm_usage`, `test_ingestion`, `test_openai_temperature`, `test_pipeline_budget`, `test_admin`, `test_source_content`, `test_detection`, `test_research`, `test_requeue_pending` — 117 passed en dos corridas (63+54) más 32 en el re-run de costos/detección/publicaciones.
- ESLint de archivos Admin tocados: ok.
- `npm run typecheck` falla por un error previo en `/seguimiento/[token]` (`robots`), no por Publicaciones.
- UI en browser: no se recorrió (servicio `web` no estaba levantado). Rutas nuevas en API responden 401 sin sesión.

## Siguiente paso

Track B según STATE. Para ver Admin: levantar `web` y abrir tablero → Publicaciones → historial → suceso (costo directo). Aplicar `alembic upgrade head` (`0014`) en cada entorno.
