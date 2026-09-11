# Handoff

Reemplazar este archivo al cerrar una tarea o al continuar en otro chat. No es un diario de sesiones.

**Fecha:** 2026-09-10  
**Tarea:** Auditor lingüístico (payload mínimo) + claim/cobertura de la declaración de la jueza. Sin ampliar alcance, sin eval paga.

## Objetivo de este chat

1. Sol solo detecta sesgo de lenguaje. El modelo no recibe ArticleContext, claims, Verification ni cobertura.
2. La declaración de la jueza es un claim distinto de la resolución; excerpt literal del documento; cobertura incompleta si falta ese respaldo.

## Avances

- `article_audit.md` y `_audit_user_prompt`: titular, bajada, cuerpo, `body_blocks`. Rewrite conserva el cap y pide preservar datos/citas.
- `structural_findings` + `merge_audit_result` siguen en código. Aprobar lenguaje ≠ certificar hechos.
- Extract: split resolución vs dicho; `salvage_excerpt` si el excerpt del LLM no está en el cuerpo (sin relajar `excerpt_in_source`). Expected central del utterance no se cierra con la condena ni con la misma persona.

## Limitaciones

No se llamó a un LLM real de auditoría. Track B sigue abierto.

## Pendientes

Track B. Eval paga. Dashboard Admin de `expected_central`.

## Archivos relevantes

`prompts/article_audit.md`, `services/audit_service.py`, `services/claim_coverage.py`, `services/claim_service.py`, `prompts/claim_extraction.md`, `tests/test_audit.py`, `tests/test_editorial_evidence.py`.

## Pruebas

Desde `apps/api` (Postgres+Redis):

```
python -m pytest tests/test_audit.py tests/test_audit_policy.py tests/test_editorial_evidence.py tests/test_verification_plan.py tests/test_claims.py
```

## Siguiente paso

No reabrir el auditor para hechos. Si la nota de la jueza ya está publicada, republicar solo si el texto o los claims de esa versión cambian.
