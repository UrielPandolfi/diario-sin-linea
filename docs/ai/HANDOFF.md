# Handoff

**Fecha:** 2026-09-21

**Tarea:** Correcciones post-revisión del lote y `f87c58f`. No merge. No deploy. No reproceso pago.

## Qué quedó

Se conservó el pairing de `f87c58f` (fingerprint, no reutilizar otro fingerprint, skip `verification_not_paired`, `based_on` real). El export `lote-post-c-chain.json` se conserva; la copia corregida es `.editorial-evals/lote-post-c-chain-corrected.json` (`selection_method: c11_explicit_version`, gitignored).

Falsos positivos corregidos en código: export V2 Milei mezclado con snapshot V1; atribución ANDIS de la misma afirmación; match duración Pilar; match secretario/hambre Jerez; transferencia Granja700 caracterización→hecho cuando el titular solo afirma el hecho; skipped fingido como atribución.

Bloqueo conservado: Jerez `7d7a8812` en titular sin atribución.

Indeterminados: Pilar `f276190c`; Granja700 `529b15f0` (1.200); snapshots V2 unpaired (Milei `d7894ad7`, Granja700 `374b6916`).

V1 Milei (`d7894ad7`) claim `12b66950`: en DB hay dos `Source` de Página/12 (RSS sin `domain` + research `pagina12.com.ar`) contados como `known_independent_count=2`. Identidad alineada a la regla vigente de un solo medio. **No** se reescribió V1. Independencia pendiente de revisar; corrección editorial solo si se decide usar `EditorialService.revise`.

`last_written_run` / `claims_snapshot_for_version` ignoran `unaudited_candidate`. `_reporting_origin` usa el host normalizado. `auto_poll_enabled=false`. Suite API: 789 passed (2026-09-21).

## Pendiente

Reproceso mínimo (no ejecutado):

- ANDIS: reauditar el mismo candidato si, tras quitar los falsos positivos, no queda otro HIGH.
- Jerez: el titular sigue sin atribuir la identificación. Corregir con `EditorialService.revise` y después auditar.
- Pilar y Granja700 V1 (1.200 / principal skipped): resolver el contrato faltante; reauditar el mismo snapshot incompleto no lo completa.
- Versiones con snapshot vacío (Milei V2, Granja700 V2): nueva versión con verificación compatible; no rellenar el snapshot vacío.
- Pollos `4704ee4e` y Milei NY `e362ee90` siguen necesitando Verification SUCCESS del fingerprint actual.
- Connection error de Verification: sin retries nuevos.
- Revisión de merge de Track C sigue aparte.
