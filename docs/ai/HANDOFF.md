# Handoff

**Fecha:** 2026-09-16

**Tarea:** Dedup ambigua con DeepSeek (sin exigir geo extraída); suite; smokes A–D smk5ds.

## Código

- Bajo LOW: si no hay contradicción estructurada, tipos compatibles, años no disjuntos, y hay overlap de proceso **o** entidades nombradas → DeepSeek. **No** exige `province`/`locality`.
- Banda LOW–HIGH: Voyage ya filtró; DeepSeek salvo conflicto o tipos incompatibles.
- ≥ HIGH sin conflicto: auto-merge, sin LLM.
- Schema `AmbiguousDedupDecision`: `SAME_EVENT` asocia; `DIFFERENT_EVENT` / `UNSURE` crean Event. Rol `AMBIGUOUS_DEDUP` reutiliza el adapter DeepSeek (`OpenAIStructuredProvider` + `json_object`). Si faltan env, cae a `CLAIM_RESOLUTION`.
- LOW=0.72 HIGH=0.88 y Voyage no se tocaron. Ni Writing/Audit, MaterialChangeDetector, auto-publish, claims ni verification.

Suite API: **607 passed**.

## Smoke smk5ds (URLs nuevas, rebuild horneado, `AMBIGUOUS_DEDUP=deepseek/deepseek-chat`)

**A** SourceItem `7a2e57ec` → Event `b3b046b5-1d1b-4a5a-8fcb-824e423c6661` (`no_candidates`). V1 publicada. API 200.

**B** SourceItem `6b5459ab` → **mismo Event**. `best_score=0.712` (<0.72). `path=ambiguous_below_low`. Señales: `compatible_type`, `shared_entities`, `shared_process` (`fiscal`, `reduc`). DeepSeek **llamado**, `SAME_EVENT` conf 0.85. B extract: `province=null` `locality=null`. Track B escribió y publicó **V2**. API 200, 2 fuentes, titular del 8%.

**C** SourceItem `97ffa7fd` → Event nuevo `5f1cd620-37b2-42e7-be7c-e5970cc30e76`. Score vs A `0.422`. DeepSeek `DIFFERENT_EVENT`. V1 publicada. API 200.

**D** SourceItem `a1f652f7` → **mismo Event que C**, `embedding_high:0.916`, sin DeepSeek. Confirmación; no hubo Writing V2.

## Residuos

- C llamó DeepSeek contra el suceso tributario a 0.422 por `shared_entities` (token de organismo). DeepSeek acertó DIFFERENT.
- Uso `ambiguous_dedup` en B no quedó tasado (`estimated_cost_usd=None`).
- C pública muestra 3 `sources` (2 ítems eval + uno extra de pipeline).
