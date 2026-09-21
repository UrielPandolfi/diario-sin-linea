# Handoff

**Fecha:** 2026-09-21

**Tarea:** Prueba dirigida post-correcciones (ANDIS reaudit + Milei versión nueva). No merge. No deploy. Polling apagado. No se publicaron estas pruebas.

## Qué quedó

**ANDIS** (`07e56d84`) V1, mismo texto: Audit `passed=true`, `rewrite_count=0`, `version_after=1`. Desaparecieron los HIGH `surface_attribution` / `surface_categorical` de `5822cdcf`. No quedó otro HIGH; solo LOW `surface_indeterminate`. El artículo quedó `READY_FOR_REVIEW`, **sin publicar** (la corrida fue in-process, no Celery).

**Milei** (`d7894ad7`): había Verification compatible (`54bc6020`, fp `cdfe8cf0`). Writing no abría V3 sin un disparo: `no_material_change` + `unaudited_candidate` reauditaría V2 vacía. Se añadió `verification_now_paired` (versión nueva, no backfill). V3 Writing `888d5452` registra `verification_run_id=54bc6020`, `coverage_run_id=6be346ab`, `based_on=6be346ab`, 7 decisiones, `stale=false`. V2 unpaired se conserva. `published_version=1`. GET público sigue el titular y el snapshot de V1 (2 claims). Independencia de V1 (`12b66950`) sigue pendiente de revisar.

Granja700 no se usó: no tiene V1 publicada.

`auto_poll_enabled=false`. Tests de `verification_now_paired`: par compatible escribe V3; sin par no; repetir Writing no crea V4; V1/V2 conservan texto y snapshot (`test_snapshot_pairing.py`).

## Pendiente

- Publicar ANDIS (Audit passed, `READY_FOR_REVIEW`) solo si se decide.
- Auditar Milei V3 por el flujo habitual, sin publicar (`AUTO_PUBLISH` apagado).
- Jerez: atribuir identificación con `EditorialService.revise` y después auditar.
- Pilar y Granja700 V1 (1.200 / principal skipped): completar contrato.
- Granja700 V2 unpaired: no tiene live publicado; no se tocó.
- Pollos `4704ee4e` y Milei NY `e362ee90`: Verification SUCCESS del fingerprint actual.
- Connection error de Verification: sin retries nuevos.
- Revisión de merge de Track C sigue aparte.
