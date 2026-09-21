# Handoff

**Fecha:** 2026-09-21

**Tarea:** Diagnóstico del lote real posterior a Track C (10 entradas del poll `0b417818`). No merge. No deploy. No reproceso pago.

## Qué quedó

La portada mezclaba 2 artículos QA (`traceqa-*.test`), 2 publicaciones del cluster Beat 04:01 UTC (Ley BA `5a27192d`, Caulo `62fe3b38`) y la V1 de Milei World Tour (`d7894ad7`). Esa V1 sí pasó Audit; la V2 quedó bloqueada. Los fixtures QA están `is_monitored=false`; `auto_poll_enabled=false`. Export: `.editorial-evals/lote-post-c-diag.json` (antes de tocar código) y `.editorial-evals/lote-post-c-chain.json` (cadena, gitignored).

Bug demostrado: `pair_from_runs` exigía `based_on_claim_run_id ==` la claim_resolution más nueva. Un `source_already_extracted` con el mismo `claims_fingerprint` dejaba Writing sin par; persistía snapshot vacío (`contract_unpaired` + `surface_contract_incomplete`). Corrección: emparejar Verification SUCCESS por fingerprint; no reutilizar otro fingerprint; no escribir candidato si hay claim_run sin par; `last_written_run` ignora `written=False`. Tests: `test_snapshot_pairing.py`. Suite backend: 777 passed.

C5 de atribución/categorización en Andis (`07e56d84`) y Pilar (`e134e571`) es bloqueo justificado. Connection error de Verification: transporte OpenAI sin HTTP status; Celery marca la tarea succeeded porque `_fail` captura; no se agregaron retries.

## Pendiente

Reproceso mínimo (no ejecutado): pollos `4704ee4e` y Milei NY `e362ee90` necesitan Verification SUCCESS del fingerprint actual y un Writing nuevo; Milei V2 / Granja 700 V2 con el mismo fingerprint pueden reescribirse sin LLM de verify. No reintentar los cinco FAILED. Imágenes api/worker/beat siguen en el build 03:37 UTC (código del lote); el arreglo está en el working tree / commit, no dentro de esos procesos hasta rebuild. Revisión de merge de Track C sigue aparte.
