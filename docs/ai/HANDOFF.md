# Handoff

Reemplazar este archivo al cerrar una tarea o al continuar en otro chat. No es un diario de sesiones.

**Fecha:** 2026-09-13  
**Tarea:** Un hecho reportable puede quedar `SUPPORTED` (y a veces CHECKED) por periodismo independiente, sin exigir fuente primaria a casi todo y sin «dos medios = verdad».

## Objetivo de este chat

Ajuste de política de resolución/verificación: `reporting:{host}` como procedencia demostrada; primaria solo cuando `requires_authoritative_source`; CHECKED por `independent_reporting` vedado en acusaciones sensibles y claims autoritativos. Conservar `SINGLE_SOURCE`, `CONFLICTING`, `DISPROVEN` endurecido, reprints y atribución vs verdad subyacente.

## Avances

- Origen: HTML extraído + fetch ok → `reporting:`; agencia/comunicado/atribución explícita colapsa; reprint por cuerpo (no título).
- `requires_authoritative_source` + `heuristic_plan` / `apply_primary_requirement` / `clamp_supported_status`.
- `is_strong_verification(..., claim=)` fail-closed; tarjeta sin copy universal de primaria ausente; `SupportKind` en el contrato.
- Tests: `test_independent_reporting.py`; techos de Federman/tarifas/Mendoza/`material_normas` conservados.

## Limitaciones

No hay eval paga ni recheck del claim `925ddcf5`. Heurísticas de acusación/cifra material son conservadoras y pueden pedir primaria de más. Detección de cable de agencia depende de encuadre explícito en el texto.

## Pendientes

Track B. Eval paga. Dashboard Admin de `expected_central`. Si se reabre un suceso real, republicar solo si cambia el texto o los claims de esa versión.

## Archivos relevantes

`services/information_origin.py`, `services/verification_policy.py`, `services/verification_plan.py`, `services/verification_outcome.py`, `services/claim_service.py`, `services/claim_card_presentation.py`, `schemas/editorial_evidence.py`, `prompts/claim_resolution.md`, `prompts/verification.md`, `prompts/verification_plan.md`, `tests/test_independent_reporting.py`, `docs/ai/DECISIONS.md`, `docs/ai/STATE.md`.

## Pruebas

Desde `apps/api` (Postgres+Redis):

```
python -m pytest tests/test_independent_reporting.py tests/test_verification.py tests/test_verification_plan.py tests/test_editorial_evidence.py tests/test_evidence_posture.py tests/test_pipeline_politics.py
python -m pytest -q --tb=line
```

## Siguiente paso

No relajar `requires_authoritative_source` para designaciones, tarifas, fallos o cifras materiales. No tratar dominio distinto como independencia si el texto nombra agencia, comunicado u origen atribuido.
