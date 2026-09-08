# Decisiones vigentes

Solo políticas con evidencia de intención (spec, test que las fija, comentario en código o `.env.example`). El cableado y los leftovers están en `STATE.md` y `pipeline.md`; no preservar un comportamiento solo porque existe.

## Producto y arquitectura

- La unidad es el **suceso** (`Event`); el artículo es la representación actual. Varias publicaciones pueden ser evidencia del mismo hecho (modelos `Event` / `EventSource` / `SourceItem`).
- Monolito modular + workers Celery; no microservicios.
- Código determinista para gates, locks, identidad e índices; LLM para extraer, comparar, clasificar, redactar o auditar (`editorial_gate.py`, `pipeline_lock.py`, `providers/`).

## Publicación

- Se publica si el último audit `SUCCESS` tiene `passed=true` sobre `current_version` (`PublishService._audit_passed_for_current`).
- Spec #85 (comentario en `.env.example`) y `test_auto_publish_flag_does_not_gate_passed_chain`: **`AUTO_PUBLISH` no es ese gate**; si Sol aprueba, el worker encola publish. Que el setting no se lea en runtime es un hallazgo de STATE, no una invariante extra.

## Gate editorial

- Ámbito: asuntos públicos y país `editorial_country_code` (default `AR`), salvo `argentina_relevance` (`evaluate_editorial_gate`, `test_editorial_gate.py`). Política nacional/provincial fuera de Rosario **pasa** en tests. El README que dice “solo Rosario” está desactualizado.

## Artículo y versiones

- Un `Article` por `event_id` (`uq_articles_event_id`).
- Update material sobre un publicado: working copy `DRAFT`; el live sigue en `published_version` hasta un audit aprobado (`writing_service.py`, `test_published_update_keeps_live_until_passed_audit`).
- Issues del audit autónomo viven en `pipeline_runs.metadata_json` (`audit_service.py`). `Correction` se crea en revisión editorial (`editorial_service.py`), no en el loop Sol→rewrite.

## Concurrencia y providers

- Un solo `RUNNING` entre writing, auditing y publishing (índice en `0009_publishing.py`, `pipeline_lock.py`, pre-check admin).
- Anthropic no es auditor: `registry.py` rechaza `AUDITING` + anthropic; `.env.example` lo documenta.
- Provider y model ID por env (`core/config.py`); el dominio no hardcodea IDs de vendor.

## Claims (M5, con tests)

- `SUPPORTED` exige respaldo de al menos dos dominios independientes; evidencia en `ClaimEvidence` (`claim_service.py`, `test_claims.py`).
- Merge por `assertion_key` / agrupación por `comparison_key`.
