# Handoff

**Fecha:** 2026-09-22

**Tarea:** Comprobar La Tablada y Esteche con el código post-fixes, sin commit y sin publicación automática.

## Resultado

Sin commit. API/worker reconstruidos; `AUTO_PUBLISH=false`; Beat no corre; `auto_poll_enabled=false`. Backup `.editorial-evals/backups/sin_linea-two-case-precheck-20260922T0321Z.dump`. Informe `.editorial-evals/two-case-check.json`.

La Tablada (`58759b17`, artículo `fa0fa66a`): V3 candidata, live V2. Claim `37f7556a` («disparo durante el tiroteo») ya no es Confirmado: `SINGLE_SOURCE`, ficha **Respaldo limitado**. Audit V3 bloqueó por C5 de bajada, no por ese claim.

Esteche (`bb76b7a6`, artículo `b8343be8`): V3 candidata, live V2. `coverage_gap` + `central_uncovered`. Audit `passed=false`. Bloqueo correcto.

## Pendiente

- Merge Track C: decisión con estos dos casos; no hace falta otro lote RSS.
- Si se quiere reemplazar el live de Tablada, hay que resolver el `structural_block` C5 de la V3 (bajada categórica/sin atribución).
- Recuperar Esteche como publicable exige extraer y evaluar la conspiración del titular; no re-verificar secundarios.
- Duplicación Formosa (`a614745e` / `45d3c314`): trabajo separado.
