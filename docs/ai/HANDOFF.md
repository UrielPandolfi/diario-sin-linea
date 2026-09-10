# Handoff

Reemplazar este archivo al cerrar una tarea o al continuar en otro chat. No es un diario de sesiones.

**Fecha:** 2026-09-10  
**Tarea:** Etapa 3 — tarjeta pública de fuentes (`status` + `support_basis` + `demotion`). Sin migración, sin eval paga, sin republicar notas.

## Objetivo de este chat

Que el popover público muestre el contrato de evidencia (consultados vs respaldan, reprints ≠ orígenes) y no `source_count` / `llm_reason`. Histórico sin par: cobertura desconocida.

## Avances

- `claim_card_presentation.py` arma el DTO; `compact_public_claims` y Admin claims lo serializan. El frontend no recalcula independencia.
- Popover: labels editoriales, resultado+limitación, cobertura en el dialog, `<details>` por tipo. `SINGLE_SOURCE` ya no se pinta como “UNA FUENTE”.
- Admin: `INITIAL` = inicial (ingesta); `tokens_total` null si `calls==0`; claims con `verification_label` + `demotion`.
- Dedupe PERSON sufijo intra-evento; prompt de extracción: GOVERNMENT≠medio, organismo≠norma, `short_summary` sin invertir cualificadores.
- Script de lectura `scripts/list_legacy_single_source_cards.py` (no publica ni crea Correction).

## Limitaciones

Eval real no corrida. Dashboard Admin de `expected_central` diferido. Track B sigue abierto. Notas live: el serializer actualiza la card; Correction solo si el texto es material.

## Pendientes

Tratamiento de notas antiguas (revisar salida del script; reaudit del texto ≠ cambiar copy). Track B. Eval paga. Coverage Admin completa.

## Archivos relevantes

`services/claim_card_presentation.py`, `services/feed_ranking.py`, `features/article/article-body.tsx`, `api/admin.py`, `prompts/event_extraction.md`, `tests/test_claim_card_presentation.py`.

## Pruebas

Desde `apps/api` (Postgres+Redis):

```
python -m pytest tests/test_claim_card_presentation.py tests/test_editorial_label_policy.py tests/test_editorial_evidence.py tests/test_detection.py tests/test_llm_usage.py tests/test_prompt_payloads.py
```

Frontend: `npm run lint` y `npm run typecheck` en `apps/web`.

## Siguiente paso

Correr el script de notas `SINGLE_SOURCE` con varios `source_item`. Si el cuerpo/titular sigue mal, `EditorialService.revise`; si solo la card mentía, el serializer basta. No declarar el MVP aprobado.
