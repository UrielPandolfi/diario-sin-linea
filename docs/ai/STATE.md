# Estado

Revisión: 2026-09-16. Track B: dedup ambigua con DeepSeek bajo LOW si hay señales (sin exigir geo extraída), `comparison_key` de proposición para actos de habla, `AUTO_PUBLISH` como gate real. Suite y smokes reales de esta iteración en HANDOFF.

Separar: **en código** ≠ **cubierto por tests** ≠ **verificado en esta sesión**.

Separar: **en código** ≠ **cubierto por tests** ≠ **verificado en esta sesión**.

## En código y cableado

Pipeline Celery: poll → detect → (create: research | link nuevo: claims incremental) → verify → material editorial → write → audit → publish si `AUTO_PUBLISH` y Audit passed y no hold (`workers/tasks.py`). Admin puede re-disparar stages. API pública: feed, live, now, local, nearby, search, artículo por slug/`public_id` (`api/public.py`). Claims públicos del artículo live congelan status/labels al snapshot de `published_version`.

Ingesta RSS (HTML no soportado en `ingestion_service.py`). Gate editorial en detección (`editorial_gate.py`). Un `Article` por evento; versiones; `editorial_hold` bloquea el enqueue autónomo de publish.

Admin Track A: `/admin/publications` (estado actual vs ejecuciones de período), costos estimados con libro/snapshot (`0014_llm_costs`), procedencia de cuerpo (`body_source`), skip de cuota persistido, fallo histórico ≠ fallo abierto. Atribución 1:1 de `LlmUsage`; backfill de embeddings separado.

Casos de lectores y revisión editorial: routers en `main.py`, migración `0013_reader_cases`, UI `/contacto`, `/seguimiento/[token]`, `/admin/cases`. **No** pasan por Celery. `EditorialService.revise` no usa el gate de audit/publish.

Writing captura el contrato (`expected_central`, `decision_by_claim_id`, `support_basis`, `verification_incomplete`, `central_unverified`) **antes** del LLM y lo ata a la versión. Audit lee ese snapshot (`evidence_snapshot_for_version`) para invariantes estructurales; el LLM de Sol no lo recibe (solo el texto de la versión). Publish usa `latest_completed` de auditing y exige snapshot + `version_after` de **esa** versión. Un 429 `rate_limit_exceeded` se reintenta en `OpenAIStructuredProvider` (`max_retries=0` en el SDK; tope `JOB_MAX_RETRIES` y presupuesto de espera derivado). `insufficient_quota` no se reintenta. Agotar deja `FAILED` técnico (`audited=false`); el historial de runs se conserva.

## Tests que existen (no = pasados ahora)

Backend: además de la suite previa, `test_editorial_evidence`, `test_audit_policy`, `test_publication_outcome`, `test_admin_publications`, `test_llm_costs`. Frontend: lint/typecheck/build en CI; **no** hay tests unitarios web.

## Hallazgos de cableado (no decisiones)

1. **Link nuevo encola claims incremental, no research.** `already_linked` (EventSource ya existente) no reabre pipeline. Track A create sigue encolando research.
2. **`AUTO_PUBLISH` se lee** en `audit_event_article`. true + passed + no hold → enqueue publish (V1 y V2). false + passed → `READY_FOR_REVIEW`.
3. **`Event.status` READY_FOR_REVIEW / UPDATING** siguen sin usarse. La candidata se representa con `Event=PUBLISHED` + `Article=READY_FOR_REVIEW`.

## Track B — 2026-09-16

En código: `detect_event` → `resolve_event_claims(..., source_item_id)` sin research; `ClaimService._run_incremental`; detector editorial (corroboración y `proposition_corroborated` no reescriben); Writing live+delta; Audit + `AUTO_PUBLISH` para V1/V2; freeze público de claims; retry `unaudited_candidate`. Tests: `test_track_b.py`. Dedup 0.72/0.88 y Voyage no se tocaron; bajo LOW, si hay señales de coincidencia (proceso u entidades nombradas) se llama DeepSeek (`SAME_EVENT` / `DIFFERENT_EVENT` / `UNSURE`). Research de ítems ya vinculados no reabre Track B (`already_linked`). Pendiente: eval con modelos reales de esta iteración en HANDOFF; `unique(source_item_id)` en `event_sources` no se agregó; carrera de dos `detect` concurrentes no se evaluó.

## Track B histórico al cerrar A

2026-09-14: se agregaron tests de `embedding_high`, Terra y `level1_code` positivo. La evaluación controlada reprodujo dos fusiones incorrectas del caso C; luego se corrigieron con autorización del usuario (ver evaluación y corrección debajo). No se reabre research al linkear. El hueco `no_claims` (write saltea sin evaluar novedad) y los cambios factuales sin claims **siguen**. No hay `unique(source_item_id)` en `event_sources` (una publicación puede ser varios sucesos). La carrera de dos `detect` concurrentes no se evaluó. Research que adjunta ítems no los marca PROCESSED.

Research que adjunta ítems no los marca PROCESSED en ResearchService; si el ítem reingresa a Detection con EventSource ya existente, `already_linked` lo marca PROCESSED y no reabre Track B.

### Evaluación de dedup — 2026-09-14

Resultado previo a la corrección: **DEDUP NO APTO PARA MVP**, 59 passed / 2 failed. C se fusionaba por `embedding_high:0.940` y por `level1_code` al compartir Rosario + Pellegrini. El [informe de evaluación](dedup-evaluation-2026-09-14.md) conserva esa evidencia histórica.

### Primera corrección de dedup — 2026-09-14 (reemplazada)

`dedup_identity.py` comparte la comparación factual entre Level 1 y la rama alta. El ancla fuerte implementada reconoce intersección corroborada + par explícito de vehículos + mismo día/tipo/localidad. Dos PLACE genéricos ya no bastan. Contradicciones comparables de ubicación, dirección, vehículos o tiempos explícitos separados por ≥2 h excluyen al Event; se consideran candidatos alternativos y Terra no puede seleccionar uno excluido o no enviado. Payload de Terra simétrico, con fecha, país/provincia, dirección y entidades estructuradas en ambos lados.

Verificado en base aislada: **61/61 casos originales + 24 pruebas adicionales = 85 passed**, un warning preexistente de Alembic. Fixtures y regresiones de C intactos (comparación AST); solo se fortaleció el contrato de payload de D. A/B conservan 1 Event; C da 2 en todas sus variantes; D conserva ambas decisiones. No se tocaron thresholds (0.72/0.88), ventana (72 h), extracción, gate editorial ni actualización de resumen/embedding al vincular. El gate sigue descartando los choques comunes antes de dedup; los tests exclusivos de identidad aíslan ese gate. Datos vivos intactos. Voyage/Terra reales y concurrencia siguen sin validar; pasar estos tests no calibra la identidad semántica en producción. Trazas en `.editorial-evals/dedup-fix-20260914/`.

### Simplificación autorizada de dedup — 2026-09-14 (vigente)

La revisión rechazó la especialización en choques y el veto temporal universal. Se retiraron sinónimos/regex de vehículos y colisiones, anclas por par de vehículos/intersección/PLACE y toda inferencia de precisión mediante HH:MM. `compare_identity` ahora solo devuelve diferencias comparables de país/provincia/localidad y dirección explícita; no afirma identidad por ausencia de conflictos. No hay veto temporal porque el esquema no aporta precisión ni puntualidad. Se conservan formatos equivalentes de dirección e intersecciones invertidas.

Level 1 solo puede vincular por una URL ya asociada; `_level1_match` retorna None porque el modelo actual no tiene un identificador único del suceso. URLs distintas continúan a embeddings/Terra. La protección de score alto, candidatos alternativos, payload simétrico y selección restringida de Terra se conservan. El score alto aún puede vincular cuando no se detectan contradicciones estructurales; esto no equivale a identidad factual demostrada ni está calibrado con Voyage real.

Verificado en base aislada eliminada al terminar: **93 passed (18.02 s) + 2 integraciones (3.36 s)**; solo warning preexistente de Alembic. A/B: 1 Event por embedding alto controlado. Todas las variantes originales de C: 2 Events; C alto se excluye por dirección, sin depender de tiempo/vehículos. D conserva EXISTING_EVENT/NEW_EVENT y payload simétrico. Seis casos políticos recorren DetectionService con el gate real: mismo anuncio por embedding/Terra; anuncios en direcciones diferentes excluidos con score alto/ambiguo; misma estructura con identidad ambigua decidida por Terra; horas aproximadas distintas no excluyen al candidato. Otros tres tests de candidatos alternativos/IDs descartados también usan anuncios y direcciones numeradas.

Fixtures originales A/B/C/D, funciones de C, expectativas de persistencia y prueba de D intactos por AST. A/B dejan de exigir una ruta interna. Sin xfail ni skips. Hashes de config, .env, Voyage provider, prompt de extracción, prompt de Terra y test_prompt_payloads intactos. No se tocaron datos vivos ni etapas posteriores, ni se invocaron providers reales. Evidencia: `.editorial-evals/dedup-generalized-20260914/`.

## Claims / verify / audit — etapas 1–2 en código; UI y eval no

2026-09-12: Claims/Verification incorpora `proposition-comparison-1`: conserva atribución y trayectorias, usa UNKNOWN_PERIOD sin inventar fechas y exige contradicción pertinente antes de DISPROVEN. Recheck por ID conserva runs y no publica. 149 tests focalizados pasaron en base separada; reevaluación real del claim `925ddcf5-e07a-47c6-a30e-e39477ea06e2`: DISPROVEN → SINGLE_SOURCE de la atribución transmitida por La Derecha Diario, sin acreditar la comparación económica. Auditor sin cambios. Evidencias, límites y runs en [diagnóstico del claim](claim-925ddcf5-verification.md).

En código: contrato versionado en `metadata_json`, par claim↔verify, coverage/recovery, split de compuestos, packet claim-primero, independencia por `information_origin`, primaria auténtica de utterance. Tests de política con dobles (Alberto/Bregman extract-verify, y ahora write/audit/publish: gap, par desparejado, snapshot de versión, FAILED posterior). **No** demuestran que Luna/Sol reales dejen de confundir proposiciones; eval con modelos reales queda fuera (`scripts/run_editorial_eval.py`).

Etapa 3 (tarjeta pública): DTO de `support_basis`/`demotion` en `compact_public_claims` y visor mínimo Admin del mismo DTO. Eval paga no corrida. RELATED_CONTEXT sigue sin adjuntarse en research. Corridas históricas sin fingerprint se tratan como `unknown`. Dashboard Admin de `expected_central`/presupuesto **no**.

## Independencia periodística — 2026-09-13

En código: `reporting:{source_id|host}` cuenta como procedencia demostrada (HTML extraído, fetch no fallido). Origen común explícito (`wire:` / `comunicado:` / `attributed:`) prevalece sobre dominio distinto. Reprint colapsa por excerpt y por fingerprint **del cuerpo**. `requires_authoritative_source` estrecha la primaria: recuento observable y presentación de denuncia no la exigen; designación, tarifa, fallo, cifra material y acusación de verdad sí. CHECKED por `independent_reporting` fail-closed sin `claim=` y si hay acusación sensible o primaria requerida. Contrato: `SupportKind` opcional en `SupportBasis` (snapshots viejos siguen validando).

Tests de política: `test_independent_reporting.py` (14). Ajustes: snippets unknown en `test_three_unknown_documents`; denuncia sin `primary_source_required`; reprints `count≤1`; `test_evidence_posture` `known_independent_count≤1`; `test_pipeline_politics` elige el claim de cifra (recovery de cobertura crea un segundo claim por «reconoció» en el lead; no es relajación de independencia). Suite API 2026-09-13: 474 passed.

Reevaluación de techos (sin eval paga, sin recheck del claim `925ddcf5`): Federman designación/traición, tarifas, sobreseimiento Mendoza y «17.000 normas» siguen `requires_authoritative_source` + plan con primaria. Un solo medio o reprint/agencia → SINGLE_SOURCE. La presentación de denuncia ya no exige primaria. El diagnóstico de `925ddcf5` (atribución SINGLE_SOURCE, sin acreditar la comparación económica) no se reabre: utterance vs hecho subyacente se conserva; reporting no confirma el dato de The Economist.

Eval con modelos reales sigue fuera (`scripts/run_editorial_eval.py`).

## Certeza en Writing/Audit — 2026-09-13

Claims `SINGLE_SOURCE` bien resueltos se publicaban como hecho categórico en titular/lead (p. ej. síntesis «dos dirigentes tienen departamentos…»). Verification no se tocó. Writing ahora exige atribución en titular, bajada y lead y prohíbe elevar certeza al combinar claims débiles. Audit recibe `lead` explícito y debe marcar HIGH con tipos ya existentes; un cuerpo atribuido no sana el titular. Tests: `test_writing_certainty.py`. Suite API: 483 passed. Eval paga no. No se reescribió la nota viva de San José 1111 en esta sesión: el caso quedó recreado en tests.

## Event Extraction — 2026-09-14

`event_type` clasifica solo el suceso principal identificado en `what_happened`, sin exigir actualidad; contexto y antecedentes no determinan el tipo. String libre, `otro` ante duda, sin inventar hechos. Cambios: prompt + nueve casos de contrato. Comando focalizado `test_prompt_payloads.py` + `test_detection.py`: **37 passed, 1 warning** en base separada. Prueba manual de `_extract_candidate` con el texto primario real de San José 1111 y OpenAI `gpt-5-nano`: `propiedad`, asunto concreto, sin hecho inventado ni fallback a Light. No se agregó a CI. Resultado completo y anomalías (`locality="null"`, topic, atribución y roles) en HANDOFF. Event vivo `0ddb9aaa-85c0-4316-8771-67dafa017d86` permanece `homicidio`; corrección manual y eventual invalidación/regeneración de embedding pendientes. No se modificaron sus campos ni embeddings.

## Parcial / stub / posible defecto

- UI “Próximamente”: `/seguidos`, `/notificaciones`, `/guardados`; mapa en local/home; login social en `/entrar`; cuentas en perfil.
- `editorial_hold` se pone `True` en revise UPDATE/CORRECTION; el override de publish no lo pone en `False`.
- Helpers Rosario / `OUTSIDE_TARGET_LOCALITY` en el gate **no** se usan en `evaluate_editorial_gate`.
- Filas `LlmUsage` anteriores a A2: USD unknown; atribución inferida de FKs; backfill vs query de embeddings no se parte.
- `body_source` histórico sin metadata = `unknown`. Quota skip anterior a A1 no reconstruible.

README desactualizado en: “solo Rosario”, proveedores de writing/audit fijos a Claude, `MAX_VERIFICATION_QUERIES_PER_CLAIM` (código/example = 3).

## Smoke Track A/B real — 2026-09-16 (DeepSeek dedup ambigua, smk5ds)

Suite **607 passed**. Rebuild horneado, `AMBIGUOUS_DEDUP=deepseek/deepseek-chat`. Smoke A Pérez: Event `b3b046b5`, V1. Smoke B Hacienda: **mismo Event**, Voyage `0.712`, DeepSeek `SAME_EVENT`, V2 live. C educación: Event nuevo `5f1cd620` (`DIFFERENT_EVENT` vs A a 0.422). D calendario: mismo Event que C por `embedding_high:0.916`. Detalle en HANDOFF.
