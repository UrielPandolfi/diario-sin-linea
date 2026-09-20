# Handoff

**Fecha:** 2026-09-20

**Tarea:** Track C — PR C2 (presentation fiel al snapshot de la versión publicada). C3 no empezó.

## Qué quedó

El GET público de un artículo deriva status, DTO de presentación y etiquetas del `evidence_snapshot` de `published_version`. Verification live puede cambiar el Event; no cambia las tarjetas de V1 hasta publicar V2. Admin/analytics siguen en el par live. C1 se conserva: skipped no vira a complete; legacy sin `evaluation_state` no es complete; skip-shaped no usa copy evaluado.

## Validación

- Dirigidos C2 (`test_editorial_label_policy.py`, `test_public_api.py`, `test_track_b.py`, `test_claim_card_presentation.py`, `test_editorial_evidence.py`): **60 passed**
- Suite API completa: **662 passed**, 1 warning Alembic preexistente

## Pendiente

C3 y el resto de Track C. No hay migración. No backfill de ArticleVersion.
