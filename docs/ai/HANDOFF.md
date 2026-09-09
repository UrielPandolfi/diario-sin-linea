# Handoff

Reemplazar este archivo al cerrar una tarea o al continuar en otro chat. No es un diario de sesiones.

**Fecha:** 2026-09-08  
**Tarea:** Claims centrales, evidencia y verificación (etapa 1). Contrato `editorial-evidence-1`. Sin auditor, publish ni UI.

## Objetivo de este chat

Cobertura del hecho central, evaluación fiel de cada claim y decisión final alineada a procedencia informativa (no dominio). Persistencia del contrato en `pipeline_runs.metadata_json`; Writing/labels leen el **par** claim_run↔verify_run.

## Avances

- Esquemas `editorial-evidence-1` (`schemas/editorial_evidence.py`): coverage, budget, `SupportBasis`, `ClaimDecision`. Sin migración 0015.
- Extracción: drop-log, `expected_central` + match/gap, recovery con `_valid_evidence` contra el cuerpo, split de compuesto (dicho / vigencia / alcance cuando el texto lo exige).
- Verify: no-veto de centrales persistidos, presupuesto, packet con `select_source_snippet` + `body_source`, prompt claim-primero, ancla temporal orientativa (histórico/TIMELESS sin `pd`).
- Independencia: `document_key` ≠ `information_origin`; unknown no suma; reprint ≥12 tokens; utterance `authentic_primary` vs `attributed_report`.
- Par atado: `claims_fingerprint` + `based_on_claim_run_id`. Extract nueva + verify FAILED no reutiliza aprobación anterior. Recordatorio Writing si `coverage_gap`.

## Limitaciones

- Gap explícito no bloquea publish. Eval real Luna/Sol pendiente. RELATED_CONTEXT no se adjunta. Histórico sin fingerprint: `unknown`.

## Pendientes (etapa 2)

Auditor sobre el snapshot del par; UI de `support_basis`/coverage; bloqueo si `coverage_gap` o `verification_incomplete`. Track B de detección/link (STATE) sigue abierto.

## Archivos relevantes

`schemas/editorial_evidence.py`, `services/claim_coverage.py`, `services/information_origin.py`, `services/claim_service.py`, `services/verification_{service,policy,plan,outcome}.py`, `services/writing_service.py`, `services/article_context.py`, `prompts/{claim_extraction,claim_assessment,verification,verification_planner,article_writing}.md`, `tests/test_editorial_evidence.py`.

## Pruebas

Desde `apps/api` (Postgres+Redis; no hace falta rebuild de imagen si pytest corre local):

```
python -m pytest
```

374 passed (2026-09-08). Incluye Alberto/Bregman, dos URLs misma fuente, par desparejado, `test_supported_two_distinct_domains` → SINGLE_SOURCE, `test_two_proven_information_origins_can_be_supported`.

## Siguiente paso

Etapa 2 según STATE. No reintroducir «dos dominios = independientes».
