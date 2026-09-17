# Handoff

**Fecha:** 2026-09-16

**Tarea:** Fase A de portada determinista (Pillow, sin IA).

## Veredicto

Al publicar o revisar editorialmente, el sistema genera una imagen 1200×630 y la persiste en Postgres. El hero corre **después del commit** en una sesión propia: si falla, el artículo queda `PUBLISHED` sin `hero_image_url`. La API sirve el PNG; el detalle y Open Graph lo muestran; las cards del feed no.

## Tests

- `tests/test_hero_image.py`: **12 passed** (PNG 1200×630, Unicode, idempotencia, fingerprint, fallo de renderer y de persistencia no revierten publish, GET PNG + `hero_image_url` en API, editorial regenera si cambia el titular).
- `tests/test_public_api.py`: campo presente y `null`.
