# Handoff

**Fecha:** 2026-09-16

**Tarea:** corregir bloqueos de la smoke Track A/B real (audit SINGLE_SOURCE, atribución de claims, retry Exa, sellado de `llm_usages` al crear Event, HTTP 400 de structured output) y repetir la eval política.

## Resultado

Los cinco bloqueos observados se corrigieron en código y la suite API pasó **575 passed** antes de la smoke (luego +1 test de schema, 9/9 en `test_openai_temperature.py`). La repetición real: Track A **PASS**; Track B material **FAIL** por dedup (no se tocó); confirmación **FAIL** por reescritura material. No se parchearon esos dos hallazgos durante la eval.

## Fixes vigentes

- Audit: `certainty_findings` + `drop_attributed_single_as_corroborated` sobre titular/bajada/lead; el LLM no puede insistir `single_as_corroborated` si el pasaje ya está atribuido. Cap 2: el rewrite #2 se audita antes de `cap_exhausted`.
- Claims: `preserve_extracted_meaning` restaura hablante/verbo y conserva `normalized_value`/`unit` en declaraciones (no en trayectoria).
- Verification: retry HTTP transitorio en Exa; si se agota, `search_unavailable` y continúa sin inventar `SUPPORTED`.
- `seal_created_event_usages(..., session=)` usa la sesión del detect después del flush del Event.
- Structured output: no se infiere `reasoning_effort`; el JSON schema estricto elimina `$ref` con siblings y `default` (causa real del 400: `$ref cannot have keywords {'default'}`).

## Eval real (IDs locales)

| Pieza | ID |
|---|---|
| Source A Prensa | `687942a8-8355-44ae-9674-70e57e8342dc` |
| Event A (10% / 40.000) | `4ba13333-654b-4d61-b12c-dc4af5fbaed8` |
| Article A V1 | `81e082d7-60c5-4ba1-88ca-22ab0f09646b` |
| Source B Hacienda | `de91d4a3-bde1-4221-8acd-a54b5fdc6b3b` |
| Event B (8% / 52.000, **nuevo**) | `8a7ea8eb-03ed-486e-9086-dec54cbd4f2e` |
| Event confirmación | `26bdc5e8-6bfa-4ebb-95cb-b9a1a0202205` |

## Pendientes no corregidos en esta sesión

- Dedup Voyage: Source B oficial `embedding_low:0.717` (umbral bajo 0.72) creó Event aparte. No se cambió el threshold.
- Confirmación: link `embedding_high:0.917` pero Writing V2 por `new_high_claim,evidence_posture_changed` (claim SUPPORTED nuevo «El ciclo lectivo comenzará el 2 de marzo.»). Live V1 intacta.
- Deepseek `claim_resolution` sigue 400→200.
- Usages de writing/verify posteriores al create suelen quedar `event_id` null (fuera del sello de Detection).
