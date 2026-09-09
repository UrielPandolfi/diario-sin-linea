# Handoff

Reemplazar este archivo al cerrar una tarea o al continuar en otro chat. No es un diario de sesiones.

**Fecha:** 2026-09-09  
**Tarea:** Redacción, auditoría y bloqueo de publicación (etapa 2). Contrato de evidencia de etapa 1 atado a la versión. Sin UI de coverage, sin eval paga, sin migración.

## Objetivo de este chat

Writing captura el contrato de entrada **antes** del LLM. Audit y publish operan sobre ese snapshot de la versión. Invariantes estructurales (par, `coverage_gap`, centrales no verificados) bloquean sin heurística de texto. Atribuir no cierra un gap ni valida un hecho inventado.

## Avances

- Snapshot: `evidence_snapshot.py` (`capture` antes de `generate_structured`, `evidence_snapshot_for_version`, no caer al par vigente).
- Context enriquecido: `expected_central`, `decision_by_claim_id`, `support_basis`, `verification_incomplete`, `central_unverified`. Prompts writing/audit: `source_contexts` no autorizan hechos materiales nuevos; atribución solo con evidencia evaluada.
- `audit_policy.py`: estructurales vs semánticos; `merge_audit_result` sobrevive a LLM `passed=true`/`issues=[]`. Rewrite no corre si hay bloqueo estructural. Cap 2 intacto.
- Publish: `latest_completed` (SUCCESS|FAILED); exige `audited`, `passed`, `version_after` y snapshot de **esa** versión. FAILED posterior no recicla SUCCESS. Locks write/audit/publish existentes.
- Tests: `test_audit_policy.py` (Alberto, paráfrasis, `central_unverified`, par desparejado, secundario diferido, SINGLE_SOURCE, snapshot post-write, cambio de versión, FAILED posterior, atribución inventada, Bregman vía LLM). Seeds de audit/publish/cases/public con snapshot de versión.

## Limitaciones

- Eval real Luna/Sol **no** corrida. UI Admin de `support_basis`/coverage **no**. Track B de detección/link sigue abierto. RELATED_CONTEXT no se adjunta.

## Pendientes (etapa 3)

Ver [`docs/mvp/editorial-02-handoff.md`](../mvp/editorial-02-handoff.md).

## Archivos relevantes

`services/{writing,audit,publish}_service.py`, `services/audit_policy.py`, `services/evidence_snapshot.py`, `services/article_context.py`, `schemas/auditing.py`, `schemas/writing.py`, `prompts/{article_writing,article_audit}.md`, `tests/test_audit_policy.py`, `tests/editorial_snapshot.py`.

## Pruebas

Desde `apps/api` (Postgres+Redis):

```
python -m pytest
```

389 passed (2026-09-09). Incluye `test_audit_policy` y la suite previa de etapa 1.

## Siguiente paso

Etapa 3: UI de coverage/`support_basis`; eval paga con alcance/costo explícitos. No reintroducir «dos dominios = independientes». No sustituir el snapshot de la versión por el par vigente.
