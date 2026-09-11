# Decisiones vigentes

Solo políticas con evidencia de intención (spec, test que las fija, comentario en código o `.env.example`). El cableado y los leftovers están en `STATE.md` y `pipeline.md`; no preservar un comportamiento solo porque existe.

## Producto y arquitectura

- La unidad es el **suceso** (`Event`); el artículo es la representación actual. Varias publicaciones pueden ser evidencia del mismo hecho (modelos `Event` / `EventSource` / `SourceItem`).
- Monolito modular + workers Celery; no microservicios.
- Código determinista para gates, locks, identidad e índices; LLM para extraer, comparar, clasificar, redactar o auditar (`editorial_gate.py`, `pipeline_lock.py`, `providers/`).

## Publicación

- Se publica si la **auditoría final de la versión que se publica** está aprobada: último run de `auditing` **completado** (`SUCCESS` o `FAILED`, no `latest_success` a ciegas), `status=SUCCESS`, `audited`, `passed=true`, `version_after == current_version`, y el `evidence_snapshot` atado a esa versión no viola invariantes estructurales. Ausente, FAILED, desparejado, `coverage_gap` / `central_unverified` obligatorio o snapshot de otra versión → no publica (fail-closed). `version_after` reasignado no transfiere un `passed` de otro texto. Tests: `test_failed_audit_after_pass_does_not_approve`, `test_version_change_between_audit_and_publish_blocks`, `test_alberto_coverage_gap_blocks_optimistic_and_attribution`, `test_optimistic_auditor_cannot_silence_structural`.
- Spec #85 (comentario en `.env.example`) y `test_auto_publish_flag_does_not_gate_passed_chain`: **`AUTO_PUBLISH` no es ese gate**; si Sol aprueba, el worker encola publish. Que el setting no se lea en runtime es un hallazgo de STATE, no una invariante extra.

## Gate editorial

- Ámbito: asuntos públicos y país `editorial_country_code` (default `AR`), salvo `argentina_relevance` (`evaluate_editorial_gate`, `test_editorial_gate.py`). Política nacional/provincial fuera de Rosario **pasa** en tests. El README que dice “solo Rosario” está desactualizado.

## Artículo y versiones

- Un `Article` por `event_id` (`uq_articles_event_id`).
- Update material sobre un publicado: working copy `DRAFT`; el live sigue en `published_version` hasta un audit aprobado (`writing_service.py`, `test_published_update_keeps_live_until_passed_audit`).
- Issues del audit autónomo viven en `pipeline_runs.metadata_json` (`audit_service.py`). `Correction` se crea en revisión editorial (`editorial_service.py`), no en el loop Sol→rewrite.
- El LLM de auditoría (Sol) solo dictamina lenguaje y sesgo de la versión actual (titular, bajada, cuerpo, ids de bloque). No recibe `ArticleContext`, claims, Verification ni cobertura. Interpretar contexto, no lista ciega de palabras. Citas atribuidas no se neutralizan. Aprobar lenguaje no certifica hechos: `structural_findings` + `merge_audit_result` siguen en código. Tests: `test_audit_payload_is_language_only`, `test_audit_flags_evaluative_voice_and_rewrites`, `test_optimistic_auditor_cannot_silence_structural`.

## Concurrencia y providers

- Un solo `RUNNING` entre writing, auditing y publishing (índice en `0009_publishing.py`, `pipeline_lock.py`, pre-check admin).
- Anthropic no es auditor: `registry.py` rechaza `AUDITING` + anthropic; `.env.example` lo documenta.
- Provider y model ID por env (`core/config.py`); el dominio no hardcodea IDs de vendor.

## Claims y evidencia (con tests)

- Merge por `assertion_key` / agrupación por `comparison_key`.
- `SUPPORTED` exige al menos **dos procedencias informativas demostradas y distintas** (`information_origin` con prueba positiva: cita explícita a un primario de la afirmación, reprint distintivo del pasaje que sostiene el claim — overlap ≥0.85 y ≥12 tokens —, o documento constitutivo de esa proposición). Un `document_key` o dominio distinto **no** es independencia. Sin prueba: grupo `unknown`; unknown no suma a known. Clamp (`clamp_supported_status`): known≥2 → SUPPORTED; hay SUPPORTS (unknown o known=1) → SINGLE_SOURCE, no UNCERTAIN. Tests: `test_supported_two_distinct_domains` (dos hosts + excerpt corto → SINGLE_SOURCE), `test_two_proven_information_origins_can_be_supported`, `test_same_outlet_two_items_is_single_source`, `test_two_original_urls_same_informative_source_are_not_two_corroborations`, `test_three_unknown_documents_do_not_count_as_independent`, `test_reprints_and_blogs_are_not_independent_corroboration`.
- Utterance **después** de desambiguar: `authentic_primary` SUPPORTS documenta **«X dijo Y»** (SUPPORTED del dicho; CHECKED solo así). `attributed_report` no satisface `primary_source_required` del utterance ni hereda CHECKED al contenido de Y. Claim mixto (dicho + vigencia/alcance) sin split: no excepción de primaria única; requisito más estricto. La declaración de quien dicta una resolución (jueza) es un claim distinto de la decisión; un excerpt de la condena o la suspensión no respalda el dicho. Si el excerpt del LLM no está en el cuerpo, se intenta un fragmento literal del documento (`salvage_excerpt`); no se relaja `excerpt_in_source`. Cobertura central completa solo si ese utterance está cubierto. Un solo medio → `SINGLE_SOURCE`. Tests: `test_extracted_transcript_supports_utterance_not_content`, `test_video_search_hit_only_is_not_authentic_primary`, `test_attributed_report_is_not_authentic_primary`, `test_refine_plan_clamps_utterance_away_from_boletin`, `test_bregman_split_selection_and_utterance_plan`, `test_judge_utterance_kept_when_excerpt_is_in_body`, `test_judge_utterance_coverage_gap_without_body_excerpt`.
- Designación, tarifas reguladas y registro judicial siguen exigiendo primaria documental (`apply_primary_requirement`; fixtures Federman/tarifas/Mendoza).
- `unresolved=false` si la política fijó un status (incluida democión Sol→SINGLE_SOURCE). `final_reason` es de código; `llm_reason` es trazabilidad. Test: `test_sol_optimistic_keeps_policy_reason_and_resolved_false`.
- La tarjeta pública serializa un DTO de presentación (`claim_card_presentation`, leído en `compact_public_claims`) a partir de `status` + `support_basis` + `demotion` + tipos de evidencia. No re-corre `assess_origins`. Histórico o par desparejado: cobertura desconocida, sin inventar conteos. Nunca `llm_reason` al público. `SINGLE_SOURCE` no convive con copy de corroboración independiente plural. Tests: `test_claim_card_presentation.py`, `test_sol_optimistic_keeps_policy_reason_and_resolved_false`.
- Contrato `editorial-evidence-1` en `pipeline_runs.metadata_json`: par claim_run↔verify_run (`claims_fingerprint` + `based_on_claim_run_id`). Writing, labels y `is_strong_verification` leen ese par, no la última SUCCESS suelta por stage. Corridas históricas sin fingerprint: `unknown`; no CHECKED sobre verify desparejado. Test: `test_new_extract_plus_failed_verify_does_not_reuse_prior_approval`.
