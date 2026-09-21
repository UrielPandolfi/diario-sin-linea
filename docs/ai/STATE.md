# Estado

Revisión: 2026-09-21. Pendientes post-C11 (tope 50 del freeze público y visual Admin de trazabilidad) cerrados. Track C listo para revisión de merge; eso no equivale a despliegue validado.

Separar: **en código** ≠ **cubierto por tests** ≠ **verificado en esta sesión**.

## En código y cableado

Pipeline Celery: poll → detect → (create: research | link nuevo: claims incremental) → verify → material editorial → write → audit → publish si `AUTO_PUBLISH` y Audit passed y no hold (`workers/tasks.py`). Admin puede re-disparar stages. API pública: feed, live, now, local, nearby, search, artículo por slug/`public_id`, PNG de portada `GET /api/v1/media/heroes/{id}.png`, inventario SEO `GET /api/v1/sitemap-articles` (`api/public.py`). Claims del GET de artículo (status, presentation, labels, `reason_code`, scopes) salen del snapshot de `published_version`; el feed no serializa claims.

Frontend público: `SITE_URL` es el origen canónico; metadata App Router, Open Graph/Twitter, JSON-LD `NewsArticle`, `sitemap.xml`, `robots.txt`. El middleware ya no exige cookie de localidad para rastrear `/`, `/en-vivo` o `/buscar`. `/admin`, `/entrar` y `/onboarding` van `noindex`. `/buscar` es `noindex, follow`. Preview con `VERCEL_ENV` no production envía `X-Robots-Tag: noindex, nofollow`.

Tras commit de `PublishService` / `EditorialService.revise` (y fill-gap admin `already_published`), `HeroImageService.ensure_in_own_session` genera una plantilla Pillow 1200×630 y la guarda en `article_hero_images`. No entra a claims/writing/audit. `hero_image_url` null sigue siendo válido. Feed, live, nearby y búsqueda incluyen `hero_image_url` en cada card; el GET público intenta rellenar una portada faltante en sesión propia.

Ingesta RSS (HTML no soportado en `ingestion_service.py`). Beat `poll_monitored_sources` cada `monitored_source_poll_interval_seconds` (default 300) si `auto_poll_enabled` (interruptor en la barra de Admin, default activo); cada poll inspecciona `monitored_source_poll_limit` entradas recientes (default 5) antes de descargar HTML. Gate editorial en detección (`editorial_gate.py`). Un `Article` por evento; versiones; `editorial_hold` bloquea el enqueue autónomo de publish.

Admin Track A: `/admin/publications` (estado actual vs ejecuciones de período), `/admin/estadisticas` (solo lectura: embudo, descarte, Track B, etiquetas), costos estimados con libro/snapshot (`0014_llm_costs`), procedencia de cuerpo (`body_source`), skip de cuota persistido, fallo histórico ≠ fallo abierto. Atribución 1:1 de `LlmUsage`; backfill de embeddings separado.

Casos de lectores y revisión editorial: routers en `main.py`, migración `0013_reader_cases`, UI `/contacto`, `/seguimiento/[token]`, `/admin/cases`. **No** pasan por Celery. `EditorialService.revise` no usa el gate de audit/publish.

Writing captura el contrato (`expected_central`, `decision_by_claim_id`, `support_basis`, `verification_incomplete`, `central_unverified`) **antes** del LLM y lo ata a la versión. Audit lee ese snapshot (`evidence_snapshot_for_version`) para invariantes estructurales; el LLM de Sol no lo recibe (solo el texto de la versión). Publish usa `latest_completed` de auditing y exige snapshot + `version_after` de **esa** versión. Un 429 `rate_limit_exceeded` se reintenta en `OpenAIStructuredProvider` (`max_retries=0` en el SDK; tope `JOB_MAX_RETRIES` y presupuesto de espera derivado). `insufficient_quota` no se reintenta. Agotar deja `FAILED` técnico (`audited=false`); el historial de runs se conserva.

## Tests que existen (no = pasados ahora)

Backend: además de la suite previa, `test_hero_image`, `test_editorial_evidence`, `test_audit_policy`, `test_publication_outcome`, `test_admin_publications`, `test_llm_costs`, `test_sitemap_articles`. Frontend: lint/typecheck/build en CI más `npm test` (`lib/seo/seo.test.ts`, `claim-popover-copy.test.ts`, `article-body.test.tsx`). Cards públicas leen `hero_image_url`.

## Hallazgos de cableado (no decisiones)

1. **Link nuevo encola claims incremental, no research.** `already_linked` (EventSource ya existente) no reabre pipeline. Track A create sigue encolando research.
2. **`AUTO_PUBLISH` se lee** en `audit_event_article`. true + passed + no hold → enqueue publish (V1 y V2). false + passed → `READY_FOR_REVIEW`.
3. **`Event.status` READY_FOR_REVIEW / UPDATING** siguen sin usarse. La candidata se representa con `Event=PUBLISHED` + `Article=READY_FOR_REVIEW`.
4. **`DATABASE_URL` de Railway/Heroku** (`postgres://` o `postgresql://`) SQLAlchemy la trata como psycopg2. El runtime es `psycopg[binary]` v3; `Settings` reescribe a `postgresql+psycopg://`.

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

## Track C1 — evaluation_state — 2026-09-20

En código: `ClaimDecision.evaluation_state` opcional en `editorial-evidence-1` (`complete` | `skipped` | `pending` | `failed`). Lectura: campo ausente o inválido → `None` (unknown/legacy), nunca `complete`. Verification SUCCESS escribe `complete` en Sol, cheap assessment, `skipped_search` dirigido y skip numérico; `skipped` en veto / `policy_skip` / `budget` / `outside_recheck` (y cualquier claim del evento sin decisión). No se escribe `pending` ni `failed` por claim: un fallo de verify sigue siendo `PipelineStatus.FAILED` sin `decision_by_claim_id` usable; assessment `None` escala a Sol. `Claim.status` no cambia por skip. Presentación pública: no evaluado → «Sin evaluación disponible» (pending/failed/skipped si el estado está persistido); `SINGLE_SOURCE` completo con respaldo admitido → «Respaldo limitado», sin respaldo admitido → «No confirmado». `compact_verification` omite skipped/pending/failed para no cambiar el prompt de Writing. Sin migración; sin backfill.

## Track C2 — presentation fiel al snapshot publicado — 2026-09-20

En código: `GET /api/v1/articles/{key}` arma claims con `compact_public_claims(..., freeze_to_version=article.published_version)`. Esa versión es `PublishService` (`published_version = current_version` al publicar), no el Writing/Verification más reciente. El freeze lista solo corridas writing/auditing atadas en JSONB a esa versión (`list_snapshot_binding_runs`; sin tope de recencia) y después `evidence_snapshot_for_version` → `view_from_evidence_snapshot` (decisiones, selected/sol del `article_context.verification`, primary desde `support_basis.primary_access`, skipped_search desde `llm_reason`). No usa `list_for_event(limit=50)`, ni la corrida más reciente, ni un fingerprint coincidente. Membership = ids del snapshot ∩ `claim_ids` del body publicado; un claim nuevo del Event no entra en V1. `_VersionClaim` no rellena status/texto/SPO/evidencia con el Claim live. Labels (`CHECKED` incluido) usan esa view y esos proxies; la policy no cambió. `compact_public_claims` sin freeze y Admin `_claims_out` siguen live. Preview admin de versión no serializa claims. Sin migración, sin backfill, sin LLM extra.

Limitaciones de datos no conservados: snapshot ausente → ids del body, status default `SINGLE_SOURCE`, copy «Sin evaluación disponible», sin Verification live. `source_item_id` de evidencia congelada es `snapshot:{ref}`. `skipped_search` numérico no queda en el snapshot: CHECKED de un SUPPORTED numérico puede inferirse distinto. SPO/texto ausentes en el snapshot no se reconstruyen del Event actual (DISCREPANCY/FALSE_CLAIM de esa versión pueden faltar). Una decisión skip-shaped (`llm_reason` veto/policy_skip/budget/outside_recheck) sin `evaluation_state` no usa copy evaluado.

## Track C3 — reason_code y scopes deterministas — 2026-09-20

En código: `ClaimDecision` persiste `reason_code`, `verified_scope` y `unsupported_scope` (opcionales). `reason_code_for` mapea Demotion, status post-gate de contradicción, `SupportKind` y conteos de procedencia; `final_reason` es `render_reason(code, context)`. El texto entero como `verified_scope` exige `SUPPORTS` persistido; `SINGLE_SOURCE` sin ese respaldo deja ambos scopes `None`. Un `claim_fragment` de QUALIFIES que es subconjunto propio del texto evaluado puede fijar `verified_scope`; no hay split del resto (`unsupported_scope=None`, alcance no determinado). QUALIFIES sin fragmento: ambos `None`. El GET solo serializa C3 si `evaluation_state=complete` (skipped/legacy/unknown no presuponen evaluación). Writing compacta sin esos campos. Independencia, `clamp_supported_status`, `authentic_primary` y umbrales de contradicción no cambiaron. Sin migración ni LLM extra.

Limitación: no hay componente estructurado B, así que C3 no representa `unsupported_scope=B` salvo que C8 haya separado proposiciones. QUALIFIES sigue sin restar strings. `CONFLICTING`/`DISPROVEN` describen el status ya pasado por los gates (C7 comparabilidad / `valid_contradiction`); C3 no reabre esa comparación. Primaria auténtica de un utterance no se mapea a `INDEPENDENT_CORROBORATION`.

## Track C4 — public_rendering — 2026-09-20

En código: `PublicRendering` opcional en `ClaimDecision`. Función pura `public_rendering_for` (sin DB, LLM ni texto del artículo). Solo `evaluation_state=complete` produce flags bool; skipped/pending/failed/legacy → `None` (permisos no determinados, no denegación evaluada). Persistido en la decisión y leído del snapshot de la versión (C2); snapshot sin el campo → `None`, sin backfill. Writing compacta sin el contrato. C5 aplica el contrato al draft; independencia y status epistemológico no se recalcularon.

Limitación: QUALIFIES sin fragmento usable sigue sin autorizar categórico del compuesto; `unsupported_scope` permanece indeterminado si no hay split seguro.

## Track C5 — superficie y coverage del titular — 2026-09-20

En código: `surface_validation_findings` (tras los invariantes previos de `structural_findings`) comprueba headline, summary y lead de la versión contra `public_rendering` del snapshot atado a **esa** versión (`evidence_snapshot_for_version`; no Verification live ni el snapshot de V1 al auditar V2). Lead = primer `body_block` (`block_plain_text`) o, si no hay bloques, el primer párrafo. Findings: `surface_attribution`, `surface_categorical`, `surface_independent_language`, `headline_uncovered`, `surface_contract_incomplete` (HIGH, `action=REVIEW`, en `_STRUCTURAL_REASONS` → `structural_block`, sin rewrite ni ciclo Writing) y `surface_indeterminate` (LOW/CLARITY, no bloquea). Matching: EQUIVALENT valida; PARTIAL/mención de tokens = indeterminado. Coverage: el núcleo del titular debe equivaler a un claim material (HIGH, o no-LOW si no hay HIGH). Skipped/`public_rendering=null` → contrato no determinado (`surface_contract_incomplete`); complete/legacy sin flags → incompleto, no PASS. Un hecho equivalente no se veta por un utterance hermano (p. ej. recovery de «reconoció») ni licencia una caracterización distinta. `PublishService._audit_passed_for_current` vuelve a correr `structural_findings` sobre el texto actual; una edición del candidato exige re-auditoría (`version_after`). `revise` humano no entra a Audit. Sin migración, sin backfill, sin LLM extra. Tests: `test_surface_validation.py` y fixtures de writing/audit/publish/Track B.

Limitación del matching: overlap ≥0.6 con bucket `other` puede marcar EQUIVALENT un utterance de recovery y un titular de hecho; C5 no repara Extraction. El marcador de atribución debe cubrir esa afirmación (trailing en la misma cláusula vale; `mientras que` no transfiere el marker; el punto de miles no parte la oración). No hay embeddings ni umbral semántico nuevo.

## Track C6 — admisión del assessment barato — 2026-09-20

En código: `assessment_has_support` deja de mirar el `SUPPORTS` crudo del modelo. Cuenta solo juicios cuya admisión en `comparison_checks` quedó `SUPPORTS` (el mismo `_admit_relation` de utterance/trayectoria/conteo regulatorio/contradicción). Ese flag alimenta el status barato (`apply_primary_requirement`) y `needs_sol_after_assessment`. Un `SUPPORTS` rechazado no borra otro admitido. La suficiencia (independencia, primaria, `authentic_primary`) no cambió. `assessments[]` sigue siendo el dump del modelo (incluye `DOES_NOT_ESTABLISH`); `_apply_judgements` registra DNE en `comparison_checks` con `admitted=None` y no crea `ClaimEvidence`/`EventSource`. Un assessment DNE válido escribe `evaluation_state=complete`; `assessment=None` (sin paquete o error) no se guarda como DNE y escala a Sol. QUALIFIES admitido no es soporte total. Sin prompts nuevos, sin rondas extra, sin migración. Un `UNCERTAIN` cuyo único SUPPORTS crudo es rechazado ahora toma el escalado a Sol que ya existía (antes se evitaba). Tests: `test_verification_plan.py`, `test_proposition_comparison.py`, `test_verification.py`.

Limitación: si el modelo etiqueta mal la relación semántica, C6 no la corrige con heurística narrativa; eso quedaría para un PR de prompt.

## Track C7 — CONFLICTING solo entre proposiciones comparables — 2026-09-20

En código: `_reconcile_competing_values` y `_reconcile_verified_competitors` exigen `conflict_comparability` (helper en `evidence_comparison.py`) antes de marcar `CONFLICTING`. Dimensiones: sujeto, predicado, `occurred_at` y/o período explícito en el texto, unidad/base si es cuantitativo (mensual vs interanual, % vs puntos), ámbito en `object_text` cuando ambos lo tienen. `comparison_key` compartida no basta. Publicación ≠ período del dato: el reloj de competidores ya no usa `published_at` si falta `occurred_at`. Pares, no el grupo entero. Utterance vs contenido y actos de hablantes distintos no se contradicen solos; un `CONTRADICTS` comparable sobre el acto de habla sí se conserva. `SUPPORTS`+`CONTRADICTS` o el status propuesto del resolver/Sol no fijan conflicto si el excerpt o el par no son comparables. Un `CONTRADICTS` no admitido (C6) no reaparece. Al descartar el par no se asigna `SUPPORTED`. `DISPROVEN`/`valid_contradiction` no se relajaron. Decisiones `complete` se resincronizan si Verification cambia el status; `skipped` no pasa a `complete`. Sin prompts ni LLM extra. Tests: `test_claims.py`, `test_proposition_comparison.py`, `test_verification.py`.

Limitación: no hay campo estructurado de período/ámbito/base aparte de `occurred_at`, `unit`, SPO y el texto; si el extractor no los llena, el par queda inconcluso. No se infiere tiempo ni se convierten unidades.

## Track C8 — claims compuestos: acto y caracterización — 2026-09-20

En código: `is_mixed_proposition` reconoce, además de vigencia/alcance/fallo/denuncia, un acto de publicación o declaración más una consecuencia/reacción del narrador (fuera de comillas) y un atributo evaluativo coordinado con un acto. `split_compound_extracted` separa solo la coordinación inequívoca (`A publicó X y generó polémica`); el relativo «un mensaje que generó polémica» y el adjetivo suelto quedan mixtos. `calificó de polémica` y la caracterización dentro de una cita no se parten. Cada componente recibe evidencia filtrada: un excerpt que no alinea pasa a `MENTIONS`; `salvage_excerpt` puede restaurar `SUPPORTS` con un fragmento literal del cuerpo. `authentic_primary` solo si la proposición no es mixta y el rol es utterance; `classify_statement_row` no sella la excepción sobre el compuesto. `_FRAME_SKIP` se conserva; un acto de publicación en el titular no se descarta como marco. Coverage no inventa claims centrales de caracterizaciones vagas. Merge/fingerprint/incremental reutilizan `assertion_key`. C7: utterance y contenido separado no se vuelven `CONFLICTING`. C2: V1 congelada. Cap de Verification intacto. Sin prompts, sin rondas LLM nuevas, sin migración. Tests: `test_compound_act_characterization.py`, regresiones Bregman/jueza en `test_editorial_evidence.py`.

Limitación: no hay motor lingüístico general; cláusulas relativas, gerundios («generando polémica») y atributos vagos no se atomizan. Un «hubo polémica» no se inventa desde un adjetivo. QUALIFIES sigue sin `unsupported_scope` por resta. Claims históricos mixtos no se migran. Ajustes de `claim_extraction.md` quedan para otro PR si el extractor no trae el compuesto separable.

## Track C9 — copy público desde el contrato — 2026-09-20

En código: `claim_card_presentation` es la fuente única del copy público. Precedencia: disponibilidad de evaluación → resultado gated (`DISPROVEN`/`CONFLICTING`) → rol/alcance (parcial, mixto, utterance) → suficiencia del respaldo admitido para la proposición completa. Familias: Confirmado, Declaración confirmada, Respaldo limitado, No confirmado, En disputa, Contradicho, Sin evaluación disponible (+ pending/failed/skipped). No deriva copy de `llm_reason` ni de prosa libre. El GET público proyecta ese renderer sobre el snapshot de `published_version`; no reescribe snapshots. `demotion` sale del DTO público y permanece en Admin (`include_internal`). Conteos (`documents_consulted`, `documents_supporting`, procedencias) van en el DTO ampliado; unknown es `None`, no 0. El consumidor web lee los textos del backend y no recalcula certeza. Writing compacta sin esos textos. Tests: `test_claim_card_presentation.py`, freeze en `test_editorial_label_policy.py`, GET en `test_public_api.py`, consumidor en `claim-popover-copy.test.ts`.

Pendiente de comprobaciones anteriores (limitaciones aceptadas del track, no reabiertas aquí): relativos/gerundios; claims históricos mixtos; QUALIFIES sin `unsupported_scope` por resta; `pending`/`failed` no se escriben en SUCCESS. Verificación visual de C10 quedó en el chat, no en el repo. Visual Admin C11: 2026-09-21, viewport 1280×800, Next local `:3001` + API con el código actual (`AUTO_PUBLISH=false`, worker/beat apagados); capturas en el chat / `e:\temp\cursor\screenshots\admin-trace-*.png`. Overlay «1 Issue» de Next es de automatización Cursor (`data-cursor-ref`), no de la app.

## Track C10 — popover y panel inferior de respaldo — 2026-09-20

En código: el artículo público (`ArticleBody`) anota solo segmentos con `claim_ids` resolubles. Escritorio: popover si `(hover: hover) and (pointer: fine)` y ancho ≥768; si no, bottom sheet modal. Ambos renderizan `ClaimEvidenceList` desde `claimEvidenceCopy` (textos C9). Hover no roba foco; click/Enter fijan el popover; Escape y click exterior cierran; un solo overlay. El sheet traba scroll, atrapa foco y restaura al cerrar. `sourceKey` (`slug:published_version`) limpia el estado al cambiar de versión. Abrir no dispara fetch/Verification. `/dev/respaldo` sirve fixtures en desarrollo (`notFound` en production). Tests: `article-body.test.tsx`, `claim-popover-copy.test.ts`. Visual local: viewport 1280×800 (popover) y 390×844 (sheet) sobre `/dev/respaldo`.

Limitación: no hay Radix; el overlay reutiliza el patrón de `context-sheets` (portal + foco + backdrop). jsdom se agregó al harness web porque no había DOM runner. Verificación visual local documentada en el chat de C10, no versionada en el repo.

## Track C11 — trazabilidad por versión (Admin/export) — 2026-09-20

C2 ya persistía el snapshot por versión (`coverage_run_id`, `verification_run_id`, `claims_fingerprint`, `contract_version`) y el GET público lo congela a `published_version`. Faltaba consultarlo en Admin/export y sellar `writing_run_id` con semántica explícita.

En código: `WritingService.write` copia `writing_run_id=str(run.id)` al snapshot **después** del LLM. `GET /api/v1/admin/articles/{id}/trace` (default publicado) y `.../versions/{n}/trace` armán `article-version-trace-1` desde esa versión resuelta una sola vez (`version_traceability.py`, `list_lineage_runs` sin tope 50). `article_version` = `version_number`; `article_version_id` = UUID de `ArticleVersion`. Sin publicada, el default responde 409 `not_published` (no sustituye `current_version`). Admin muestra una sección en el detalle del suceso y descarga JSON. El GET público no gana IDs internos. Sin migración, sin backfill, sin etapa nueva de pipeline.

Mapa: campo → origen persistido → vínculo.

| Campo | Origen | Vínculo con ArticleVersion |
| --- | --- | --- |
| article_id / event_id | `articles` | `article_versions.article_id` |
| article_version | `article_versions.version_number` | identidad exportada |
| article_version_id | `article_versions.id` | UUID de esa fila |
| writing_run_id | snapshot `writing_run_id` o writing SUCCESS con `metadata.version` igual; rewrite: copiado / `version_before` del audit | no es la última corrida del evento |
| verification_run_id, coverage_run_id, based_on_claim_run_id, claims_fingerprint, contract_version | snapshot de writing o audit (`version` / `version_after`) | C2 |
| current_version / published_version | punteros del Article | contexto admin, no identidad |

Legacy: IDs conocidos se conservan; ausentes → `missing_fields`; objeto borrado → `unresolvable_fields`; stage/evento contradictorio → `inconsistencies` (no se reescribe el snapshot). `revise` editorial no inventa Writing. Tests: `test_version_traceability.py`.

C11 cerrado en código y tests dirigidos. Visual Admin de trazabilidad comprobada 2026-09-21. Eso no convierte en hechas las comprobaciones visuales de C10 ni un despliegue.

## Track C — cierre pendientes post-C11 — 2026-09-21

El tope `list_for_event(limit=50)` sí afectaba el GET público: esa consulta es newest-first de **todas** las etapas; 51 `research` posteriores dejan fuera el writing/auditing de V1, `evidence_snapshot_for_version` no halla snapshot y el freeze cae al fallback neutral (no al Verification live). Causa observable: copy/claims/labels de V1 ya no coinciden con el GET anterior al flood. Corrección: `_frozen_public_claims` usa `list_snapshot_binding_runs(event_id, version)` (writing/auditing, filtro JSONB `version` / `version_after` / `evidence_snapshot.version`, sin cap). El matcher de C2/C11 se reutiliza. `list_for_event(limit=50)` sigue en historial Admin y otros callers; no se sustituyó por otro tope. Regresión `test_public_article_keeps_v1_snapshot_after_later_runs_fill_the_50_cap` (endpoint público real, fakes). Publicar V2 cambia el GET; `/versions/1/trace` conserva la cadena de V1. Snapshot ausente / decisión vacía: `test_frozen_missing_decision_is_not_filled_from_live_verify`. Consultar no crea corridas ni versiones.

## Track C — matriz C1–C11 (cierres acreditados, sin reauditoría)

| Fase | Commit | Estado acreditado | Pendiente visible |
| --- | --- | --- | --- |
| C1 | `3523551` | Contrato determinista de causa/alcance | — |
| C2 | `efaa0a8` + este cierre | Freeze público al snapshot de `published_version` vía consulta dirigida | — |
| C3 | `3523551` (mismo corte de contrato) | `reason_code` / scopes en snapshot | `pending`/`failed` no se escriben en SUCCESS |
| C4 | `632f591` | `public_rendering` de permisos | Snapshot legacy → `None` |
| C5 | `7c98fa7` | Superficies vs contrato de esa versión | — |
| C6 | `a15310f` | Assessment barato solo con SUPPORTS admitidos | — |
| C7 | `a99e59a` | CONFLICTING exige comparabilidad | — |
| C8 | `f96eccd` | Split acto vs caracterización | Relativos/gerundios; QUALIFIES sin `unsupported_scope` por resta; mixtos históricos |
| C8b | `8dfc167` | `verified_scope` exige SUPPORTS admitido | — |
| C9 | `ee56641` | Copy público desde el contrato | Consumidor web no recalcula |
| C10 | `27692c1` | Popover/sheet sobre copy C9 | Verificación visual en chat, no en repo; Next overlay de automatización no es de la app |
| C11 | `b325852` | Export/Admin de la cadena por versión | Visual Admin comprobada 2026-09-21; no deploy |

Listo para revisión de merge ≠ despliegue validado. Limitaciones aceptadas de C8–C10 siguen.

## Lote real post-C — 2026-09-21

Diez entradas acreditadas por Redis `claimed_items` del poll `0b417818` (no «últimas 10» ni la ventana de 24 h). Siete eventos de ese lote; el cluster Beat 04:01 y los fixtures `traceqa-*.test` se excluyen del balance. `auto_poll_enabled=false`.

Causa de `contract_unpaired` / `surface_contract_incomplete` en candidatos con verify SUCCESS del mismo fingerprint: `pair_from_runs` ataba Verification al id de la claim_resolution más nueva. Un extract posterior `source_already_extracted` rompía el par; Writing persistía snapshot sin `decision_by_claim_id`. En pollos `4704ee4e` Writing se disparó cuando terminó el verify del fingerprint viejo mientras el fingerprint nuevo seguía RUNNING. `public_rendering` sí estaba en el metadata de Verification SUCCESS; C4 lo omite del DTO de Writing, no del snapshot de Audit cuando hay par.

El informe que clasificó Andis/Pilar/Jerez/Granja700 V1 como «C5 justificado» en bloque era incorrecto. El export `lote-post-c-chain.json` mezcló V2 de Milei (`d7894ad7`) con snapshot de V1 (`unaudited_candidate` + fallback de Audit sin `break`). Falsos positivos de Audit: atribución ANDIS que sí cubre esa afirmación; match laxo de duración Pilar; match secretario/hambre Jerez; transferencia Granja700 caracterización→hecho cuando el titular solo afirma el hecho; skipped fingido como atribución. Bloqueo conservado: Jerez `7d7a8812` en titular sin atribución. Indeterminados: Pilar `f276190c`; Granja700 `529b15f0` (1.200); snapshots V2 unpaired (Milei, Granja700).

Corrección: helper C11 de snapshot por versión (`export_snapshot_for_version` / `bound_export_for_version`); `last_written_run` y `claims_snapshot_for_version` ignoran `unaudited_candidate`; emparejamiento exige IDs compatibles además del fingerprint; C5 equivalencia más estricta, skipped=incompleto, atribución de la misma afirmación, certainty solo EQUIVALENT. Tests: `test_surface_validation.py`, `test_snapshot_pairing.py`, `test_version_traceability.py`, `test_independent_reporting.py`, `test_domain.py`. Suite API 2026-09-21: 789 passed. Fakes, sin providers pagos.

V1 Milei claim `12b66950`: procedencia leída en DB — dos `Source` para Página/12 (RSS `domain` vacío `6fcd5ecb` + research `pagina12.com.ar` `12bfecce`), `known_independent_count=2`. Identidad alineada a `test_same_outlet_two_items_is_single_source` (`_reporting_origin` por host; `get_by_domain` reusa RSS sin domain). V1 publicada no se reescribe. Independencia pendiente de **revisar** (corrección editorial solo vía `EditorialService.revise` si se decide). Connection error de Verification: transporte OpenAI sin HTTP status; Celery marca la tarea succeeded porque `_fail` captura; no se agregaron retries.

Prueba dirigida 2026-09-21 (sin publicar): ANDIS V1 reauditada in-process → `passed`, sin HIGH de atribución, `READY_FOR_REVIEW`. `verification_now_paired` (`a6326e1`): Writing emite V nueva si el snapshot de la candidata está unpaired y hay par compatible. Milei V3 persistida (`1ae3ff99`, verify `54bc6020`); Audit Celery `2dc2b94e` → `passed=false`, `structural_block`, `rewrite_count=0`, HIGH `surface_contract_incomplete` de `c0c73502` (skipped / `public_rendering=null`) en titular y lead. `published_version=1`. `AUTO_PUBLISH=false`. Granja700 no se tocó.

Causa de ese skip (leída en DB, no reescrita): `c0c73502` es HIGH `hecho` no documental, `SUPPORTED`, `independent_support_count=3` → `policy_selects` falso → `policy_skip`. V1 `61bae0be` lo había evaluado (`complete`) cuando aún no era well-supported; V3 copió el status live y dejó `public_rendering=null`. `compact_verification` omitió el skip; Writing lo puso en `confirmed_claims` (C6) sin decisión. C5 bloqueó bien. Código: omisión del tope de 5 ya no deja ese contrato incompleto (`live_evidence` sobre evidencia actual, sin copiar V1); Writing no trata skipped SUPPORTED como confirmado; `verification_contract_completed` escribe versión nueva cuando el par actual completa un skip del snapshot. Snapshots históricos no se tocaron. Tests dirigidos 2026-09-21: 197 passed (`test_verification.py`, `test_snapshot_pairing.py`, `test_writing.py`, `test_verification_plan.py`, `test_editorial_evidence.py`, `test_evidence_posture.py`, `test_writing_certainty.py`, `test_audit_policy.py`, `test_surface_validation.py`). Sin llamadas pagas. **Esa suite se corrió con `docker compose exec api pytest` contra el postgres vivo; `conftest.py` truncaba las tablas al cerrar `db_session`. Recuperación de `d7894ad7` el mismo día: 0 events en `sin_linea`, Verification no encolada.**

Aislamiento 2026-09-21: pytest exige `TEST_DATABASE_URL` (`sin_linea_test`); aborta si falta o si es la base de la app; el `TRUNCATE` comprueba `current_database()` antes. Worker/Beat detenidos; `AUTO_PUBLISH=false`; poll off. No hay dump/volumen restaurable con filas editoriales; `.editorial-evals` no es backup completo. `sin_linea` sigue sin events/articles/claims. Verification/Writing/Audit no se tocaron en esta corrección.

## Track C — revisión integrada C1–C8 — 2026-09-20

Hallazgo confirmado: `editorial_scopes` sellaba `verified_scope` con el texto entero si el status era `SINGLE_SOURCE`/`SUPPORTED`, aunque no hubiera `SUPPORTS` persistido. Un assessment completo cuyo único SUPPORTS era rechazado conservaba SINGLE_SOURCE y aparentaba alcance verificado. Corrección: el texto entero como `verified_scope` exige `SUPPORTS` admitido; sin él ambos scopes quedan `None`. QUALIFIES con fragmento no cambia. Tests: `test_single_source_without_admitted_supports_does_not_verify_the_claim`, `test_rejected_raw_supports_does_not_activate_cheap_support`. C9 consume esos scopes; no los recalcula.

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

### Validación final Track B (smokes smk5ds, sin cambio de código)

Circuito A–B–C–D **APTO**: B reutiliza A, V2 material, V1 intacta, `current_version=published_version=2`, sin V3; C es otro Event; D reutiliza C por embedding alto y no escribe versión ni update material.

Deuda de optimización (no heurística nueva): **`generic entity overlap may trigger unnecessary dedup call`**. C vs A a similarity 0.422 llamó DeepSeek por `shared_entities` (token de organismo); la decisión `DIFFERENT_EVENT` fue correcta.

Huecos editoriales de smk5ds **cerrados** en smk6ed (sin tocar dedup/Voyage/LOW/HIGH/versionado): (1) Verification puede persistir `ClaimEvidence` de otra jurisdicción; `geo_places_conflict` impide `EventSource` y `source_payloads` no la lista. (2) Incremental ya no mete `title_internal` con cifras viejas; 52.000/8% se persisten y 10%/40.000 siguen trazables.
