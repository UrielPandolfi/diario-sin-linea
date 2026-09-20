# Handoff

**Fecha:** 2026-09-20

**Tarea:** Track C — PR C8 (claims compuestos: separar acto y caracterización). C9 no empezó.

## Qué quedó

Un claim ya no mezcla un acto verificable con una caracterización o consecuencia de modo que el respaldo del acto confirme todo el compuesto. `is_mixed_proposition` y `split_compound_extracted` reconocen acto + reacción coordinada (`publicó X y generó polémica`); el relativo ambiguo y el adjetivo suelto quedan mixtos, sin inventar «hubo polémica». `calificó de polémica` y la caracterización citada no se parten. Cada componente filtra `SUPPORTS`; `authentic_primary` solo aplica al utterance no mixto. Salvage puede restaurar un excerpt literal del cuerpo. C7 (utterance vs contenido) y C2 (V1 congelada) se conservan. Sin cambios de prompt ni rondas LLM nuevas.

## Validación

- Dirigidos: `test_compound_act_characterization.py`, `test_editorial_evidence.py`, `test_material_attribution.py`, `test_claims.py`, `test_independent_reporting.py`, `test_verification_plan.py`, `test_proposition_comparison.py`, `test_track_b.py` — 177 passed
- Suite API completa: **741 passed**, 1 warning Alembic preexistente
- `python -m pytest -q` en `apps/api`

## Pendiente

Revisión conjunta C1–C8 (no se declara hecha por el solo paso de la suite). C9 (copy). Relativos/gerundios y atributos vagos no se atomizan. Claims históricos mixtos no se migran. Si el extractor no trae el compuesto separable, un ajuste de `claim_extraction.md` es otro PR. QUALIFIES sigue sin `unsupported_scope` por resta. No hay migración ni backfill.
