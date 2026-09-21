# Handoff

**Fecha:** 2026-09-21

**Tarea:** Cerrar el desajuste `c0c73502` (policy_skip vs Writing confirmed). No merge. No deploy. Polling apagado. No reprocesar el lote. No llamadas pagas. Snapshots históricos no se modificaron.

## Qué quedó

HIGH `hecho` well-supported omitido del tope de cinco ya no queda `skipped`+`public_rendering=null`. Verification cierra contrato con evidencia live de esa corrida (`live_evidence`, sin search/Sol, sin copiar V1). Writing no trata skipped SUPPORTED como confirmado. Si el snapshot actual está skipped y el par compatible ahora está complete, Writing emite versión nueva (`verification_contract_completed`) sin cambiar `detect_material_change`. Límite de cinco, C5 y trazabilidad se conservan.

Tests fakes dirigidos: 197 passed (`test_verification.py`, `test_snapshot_pairing.py`, `test_writing.py`, `test_verification_plan.py`, `test_editorial_evidence.py`, `test_evidence_posture.py`, `test_writing_certainty.py`, `test_audit_policy.py`, `test_surface_validation.py`).

**Milei** (`d7894ad7`) V3 y V1 no se tocaron. El bloqueo de Audit V3 sigue siendo el contrato skipped de `c0c73502`.

## Recuperar esta nota (mínimo)

Con API/worker corriendo este código, `AUTO_PUBLISH=false` y polling off: Verification admin del suceso (sin RSS ni research nuevo). Writing debería emitir V4 por `verification_contract_completed` (no reauditar V3 skipped). Después Audit de esa versión. No publicar salvo decisión. No copiar V1 a mano.

## Pendiente

- Ejecutar esa Verification+Writing+Audit de Milei cuando el stack tenga el commit.
- Publicar ANDIS solo si se decide.
- Jerez: atribuir identificación con `EditorialService.revise` y después auditar.
- Pilar y Granja700: contrato incompleto / unpaired.
- Independencia V1 Milei `12b66950`: pendiente de revisar.
- Revisión de merge de Track C sigue aparte.
