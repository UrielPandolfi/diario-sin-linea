# Handoff

**Fecha:** 2026-09-18

**Tarea:** Mostrar las portadas deterministas en el front público.

## Qué quedó

Las imágenes sí se generan post-commit, pero el lector no las veía: `card_payload` no mandaba `hero_image_url` y `EventCard` era solo texto. El detalle las pintaba solo si el PNG ya existía. Ahora feed/live/search/nearby incluyen la URL; las cards y el artículo la renderizan. Un GET público rellena portadas faltantes en sesión propia.

## Validación

- `pytest tests/test_hero_image.py tests/test_public_api.py`: **19 passed**
- `npm run typecheck` y `npm run lint` en `apps/web`: OK
- Compose local `:3000` / `:8000` están up, pero el feed público está vacío (no hay sucesos publicados para smoke visual de cards)

## Pendiente

Worker y beat en Railway. `API_URL` en Vercel para que `/api/v1/media/heroes/...` no 404. Redeploy API+web para que las notas ya publicadas tomen el backfill al abrir el feed.
