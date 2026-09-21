# Handoff

**Fecha:** 2026-09-21

**Tarea:** Aislar pytest de la base de la aplicación y evaluar recuperación tras el `TRUNCATE` de `sin_linea`.

## Resultado

Worker y Beat siguen detenidos. `AUTO_PUBLISH=false`. `auto_poll_enabled=false` (fila en `app_settings`, 2026-09-21 19:49 UTC). Volumen `diariosinlnea_postgres_data` (creado 2026-09-10) intacto: no hubo `down -v`, prune ni truncate nuevo.

Pytest exige `TEST_DATABASE_URL` (`sin_linea_test`). Si falta o apunta a `sin_linea`/`DATABASE_URL`, aborta antes de migrar o truncar. Abortos comprobados sin `TRUNCATE` sobre `sin_linea` (sigue 0 events / 1 `app_settings`). Isolation 17 passed. Suite API en `sin_linea_test`: 808 passed; 1 failed ajeno a este cambio (`test_published_update_keeps_live_until_passed_audit` → Audit `structural_block`, no `cap_exhausted`). Verification/Writing/Audit no se modificaron acá.

## Recuperación

No hay backup utilizable de Postgres. No se restauró nada sobre `sin_linea` ni se creó una base de recovery con filas editoriales.

- En el cluster vivo: `sin_linea` (app, vacía de contenido editorial), `sin_linea_test` y `sin_linea_claim_comparison_test` (0 events/articles/claims). WAL sin archivo (`archive_mode=off`).
- Dos volúmenes Docker anónimos pg16 (2026-09-15, 38.3M y 54.7M) se copiaron a instancias de inspección: solo `postgres`/`template*`, sin `sin_linea`.
- No hay `.sql`/`.dump` del medio en el repo. Los `.sql` del host son de otros proyectos (clínica, etc.).
- `.editorial-evals` se conservó (exports JSON/diagnóstico, no dump). El más reciente de lote es `lote-post-c-report.json` / `lote-post-c-chain*.json` (2026-09-21 06:25 UTC): IDs y veredictos, no filas restaurables. `milei-v3-audit.json` y `andis-reaudit.json` son trazas de una corrida, no la base.

Falta en `sin_linea`: events, articles, claims, sources, pipeline_runs, versiones (incl. `d7894ad7` / `c0c73502`). No se reingirió ni se llamó a providers.

## Pendiente

- Recuperar el contenido editorial desde una copia que aún no existe en este entorno, o reingestar cuando se autorice. No se hizo acá.
- No arrancar worker/Beat ni polling hasta esa recuperación.
