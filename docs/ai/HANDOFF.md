# Handoff

**Fecha:** 2026-09-16

**Tarea:** Cerrar los dos huecos editoriales de smk5ds (fuente pública irrelevante y 52.000 perdido). Track B dedup no se tocó.

## Veredicto

**Bloque editorial cerrado para MVP.** Track B sigue APTO. Los dos huecos de smk5ds pasan en smk6ed.

## Causas (código)

1. **Fuente pública irrelevante.** Verification persistía `ClaimEvidence` y, si el juicio era SUPPORTS/CONTRADICTS/QUALIFIES, `_attach_evidence` creaba `EventSource` ADDITIONAL. `source_payloads` listaba todos los `event_sources`. MENTIONS ya no adjuntaba; el hueco era SUPPORTS genérico de otra jurisdicción (Río Negro vs Río Norte).
2. **52.000 perdido.** El prompt incremental incluía `title_internal` con 40.000; Luna copiaba esa cifra. `salvage_excerpt` podía validar una oración sin la magnitud. No era merge `assertion_key` 52k→40k.

## Cambio mínimo

- `geo_places_conflict` (`editorial_gate.py`): si Event e ítem tienen lugares disjuntos, no hay `EventSource`. `ClaimEvidence` sí puede quedar. Defensa en `source_payloads`.
- Incremental: `_extraction_prompt(..., identity_only=True)` (sin `title_internal`); `_sources_support_figure` exige 4+ dígitos en el cuerpo/snippet.

Sin LLM nuevo. Sin tocar LOW/HIGH, Voyage, DeepSeek dedup, MaterialChangeDetector, auto-publish ni versionado.

## Tests

- `test_other_jurisdiction_generic_overlap_is_evidence_not_public_source`
- `test_geo_place_keys_distinguish_rio_norte_from_rio_negro`
- `test_incremental_keeps_historical_figures_and_persists_new_official_values`
- Suite API: **610 passed**

## Smokes smk6ed (providers reales)

Tag URL `smk6ed`. El `wait.py` de eval puede marcar idle en V1 mientras B/D siguen; la validación usó el pipeline ya terminado.

### Event A/B — `d0cf9d13-19b1-41fc-b722-db196e363b05`

- A `45b0a912` → Event nuevo (`no_candidates`), V1.
- B `c39ecf0f` → **el mismo Event**. Voyage 0.746, `path=ambiguous_band`, DeepSeek **SAME_EVENT**.
- V2 material (`new_high_claim`); `published_version=current_version=2`.
- Claims: 10% (declaración de A, `UNCERTAIN`); 40.000 de A `val=40000` `SINGLE_SOURCE`; 8% de Hacienda `val=8`; **52.000 de Hacienda `val=52000`**. No se reescribió 52.000 como 40.000.
- Fuentes públicas: prensa + hacienda eval.

### Event C/D — `c4a60246-eb98-4fc3-a216-09c8c4b6d2b0`

- C `616763bd` → Event distinto. Score 0.441, DeepSeek **DIFFERENT_EVENT**.
- D `6d43b8ed` → mismo Event, `embedding_high:0.912`. Sin V2 (igual que smk5ds: confirmación no material).
- Fuentes públicas: **2**, ambas eval (`educacion` INITIAL, `calendario` CONFIRMING).
- `rionegro.com.ar` apareció como hit de Verification; **no** es `EventSource` ni entra al API. `educacion.rionegro.gov.ar` quedó `ClaimEvidence` MENTIONS.

## Deuda (sin heurística nueva)

`generic entity overlap may trigger unnecessary dedup call` — C vs A a ~0.44 por overlap genérico; DeepSeek acertó DIFFERENT.
