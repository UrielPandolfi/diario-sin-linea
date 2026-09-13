# Estado

Revisión: 2026-09-10. Track A (observabilidad y costos Admin) está en código. Track B **no** se implementó ni se da por resuelto. Etapa 1 (`editorial-evidence-1`) y etapa 2 (snapshot de writing, invariantes de audit, bloqueo de publish) están en código y tests con dobles. Etapa 3 (tarjeta pública de evidencia / DTO de `support_basis`) está en código y tests de matriz; eval paga **no**. Dashboard Admin de `expected_central` queda diferido. 429 temporal de OpenAI en LLM estructurado se reintenta en el cliente (no en Celery ni en el SDK).

Separar: **en código** ≠ **cubierto por tests** ≠ **verificado en esta sesión**.

## En código y cableado

Pipeline Celery: poll → detect → research → claims → verify → write → audit → publish (`workers/tasks.py`). Admin puede re-disparar stages. API pública: feed, live, now, local, nearby, search, artículo por slug/`public_id` (`api/public.py`). Claims del artículo: `compact_public_claims` serializa el DTO de presentación (`claim_card_presentation`: `status` + `support_basis` + `demotion`); no `llm_reason` ni `sol.reason` como veredicto.

Ingesta RSS (HTML no soportado en `ingestion_service.py`). Gate editorial en detección (`editorial_gate.py`). Un `Article` por evento; versiones; `editorial_hold` bloquea el enqueue autónomo de publish.

Admin Track A: `/admin/publications` (estado actual vs ejecuciones de período), costos estimados con libro/snapshot (`0014_llm_costs`), procedencia de cuerpo (`body_source`), skip de cuota persistido, fallo histórico ≠ fallo abierto. Atribución 1:1 de `LlmUsage`; backfill de embeddings separado.

Casos de lectores y revisión editorial: routers en `main.py`, migración `0013_reader_cases`, UI `/contacto`, `/seguimiento/[token]`, `/admin/cases`. **No** pasan por Celery. `EditorialService.revise` no usa el gate de audit/publish.

Writing captura el contrato (`expected_central`, `decision_by_claim_id`, `support_basis`, `verification_incomplete`, `central_unverified`) **antes** del LLM y lo ata a la versión. Audit lee ese snapshot (`evidence_snapshot_for_version`) para invariantes estructurales; el LLM de Sol no lo recibe (solo el texto de la versión). Publish usa `latest_completed` de auditing y exige snapshot + `version_after` de **esa** versión. Un 429 `rate_limit_exceeded` se reintenta en `OpenAIStructuredProvider` (`max_retries=0` en el SDK; tope `JOB_MAX_RETRIES` y presupuesto de espera derivado). `insufficient_quota` no se reintenta. Agotar deja `FAILED` técnico (`audited=false`); el historial de runs se conserva.

## Tests que existen (no = pasados ahora)

Backend: además de la suite previa, `test_editorial_evidence`, `test_audit_policy`, `test_publication_outcome`, `test_admin_publications`, `test_llm_costs`. Frontend: lint/typecheck/build en CI; **no** hay tests unitarios web.

## Hallazgos de cableado (no decisiones)

1. **Link no encola research.** `detect_event` solo llama `research_event` si `created` y hay `event_id`. Vincular o filtrar no reabre research→publish. **Track B:** no verificado ni reparado en A.
2. **`AUTO_PUBLISH` no se lee** fuera de Settings. El path vivo publica por audit `passed` + no hold + gate de versión/snapshot.
3. **`READY_FOR_REVIEW` no se asigna** en servicios.

## Track B — no resuelto al cerrar A

No se escribieron tests de `embedding_high`, Terra ni `level1_code` positivo. No se reabre research al linkear. El hueco `no_claims` (write saltea sin evaluar novedad) y los cambios factuales sin claims **siguen**. No hay `unique(source_item_id)` en `event_sources` (una publicación puede ser varios sucesos). La carrera de dos `detect` concurrentes no se evaluó. Research que adjunta ítems no los marca PROCESSED.

Hasta B, “fuente agregada” >> “actualización publicada” es el cableado real. Dedup por embeddings/Voyage **no** quedó verificado en esta tarea.

## Claims / verify / audit — etapas 1–2 en código; UI y eval no

2026-09-12: Claims/Verification incorpora `proposition-comparison-1`: conserva atribución y trayectorias, usa UNKNOWN_PERIOD sin inventar fechas y exige contradicción pertinente antes de DISPROVEN. Recheck por ID conserva runs y no publica. 149 tests focalizados pasaron en base separada; reevaluación real del claim `925ddcf5-e07a-47c6-a30e-e39477ea06e2`: DISPROVEN → SINGLE_SOURCE de la atribución transmitida por La Derecha Diario, sin acreditar la comparación económica. Auditor sin cambios. Evidencias, límites y runs en [diagnóstico del claim](claim-925ddcf5-verification.md).

En código: contrato versionado en `metadata_json`, par claim↔verify, coverage/recovery, split de compuestos, packet claim-primero, independencia por `information_origin`, primaria auténtica de utterance. Tests de política con dobles (Alberto/Bregman extract-verify, y ahora write/audit/publish: gap, par desparejado, snapshot de versión, FAILED posterior). **No** demuestran que Luna/Sol reales dejen de confundir proposiciones; eval con modelos reales queda fuera (`scripts/run_editorial_eval.py`).

Etapa 3 (tarjeta pública): DTO de `support_basis`/`demotion` en `compact_public_claims` y visor mínimo Admin del mismo DTO. Eval paga no corrida. RELATED_CONTEXT sigue sin adjuntarse en research. Corridas históricas sin fingerprint se tratan como `unknown`. Dashboard Admin de `expected_central`/presupuesto **no**.

## Independencia periodística — 2026-09-13

En código: `reporting:{source_id|host}` cuenta como procedencia demostrada (HTML extraído, fetch no fallido). Origen común explícito (`wire:` / `comunicado:` / `attributed:`) prevalece sobre dominio distinto. Reprint colapsa por excerpt y por fingerprint **del cuerpo**. `requires_authoritative_source` estrecha la primaria: recuento observable y presentación de denuncia no la exigen; designación, tarifa, fallo, cifra material y acusación de verdad sí. CHECKED por `independent_reporting` fail-closed sin `claim=` y si hay acusación sensible o primaria requerida. Contrato: `SupportKind` opcional en `SupportBasis` (snapshots viejos siguen validando).

Tests de política: `test_independent_reporting.py` (14). Ajustes: snippets unknown en `test_three_unknown_documents`; denuncia sin `primary_source_required`; reprints `count≤1`; `test_evidence_posture` `known_independent_count≤1`; `test_pipeline_politics` elige el claim de cifra (recovery de cobertura crea un segundo claim por «reconoció» en el lead; no es relajación de independencia). Suite API 2026-09-13: 474 passed.

Reevaluación de techos (sin eval paga, sin recheck del claim `925ddcf5`): Federman designación/traición, tarifas, sobreseimiento Mendoza y «17.000 normas» siguen `requires_authoritative_source` + plan con primaria. Un solo medio o reprint/agencia → SINGLE_SOURCE. La presentación de denuncia ya no exige primaria. El diagnóstico de `925ddcf5` (atribución SINGLE_SOURCE, sin acreditar la comparación económica) no se reabre: utterance vs hecho subyacente se conserva; reporting no confirma el dato de The Economist.

Eval con modelos reales sigue fuera (`scripts/run_editorial_eval.py`).

## Parcial / stub / posible defecto

- UI “Próximamente”: `/seguidos`, `/notificaciones`, `/guardados`; mapa en local/home; login social en `/entrar`; cuentas en perfil.
- `editorial_hold` se pone `True` en revise UPDATE/CORRECTION; el override de publish no lo pone en `False`.
- Helpers Rosario / `OUTSIDE_TARGET_LOCALITY` en el gate **no** se usan en `evaluate_editorial_gate`.
- Filas `LlmUsage` anteriores a A2: USD unknown; atribución inferida de FKs; backfill vs query de embeddings no se parte.
- `body_source` histórico sin metadata = `unknown`. Quota skip anterior a A1 no reconstruible.

README desactualizado en: “solo Rosario”, proveedores de writing/audit fijos a Claude, `MAX_VERIFICATION_QUERIES_PER_CLAIM` (código/example = 3).
