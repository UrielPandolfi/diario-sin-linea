# Handoff

**Fecha:** 2026-09-22

**Tarea:** Portada automática con prompt DeepSeek (`IMAGE_PROMPT`) y FLUX Schnell en Replicate. Sin commit.

## Resultado

Se reemplazó la plantilla Pillow. Tras el commit de publish/revise, si `ARTICLE_IMAGE_ENABLED` y no hay `hero_image_url`, se pide un prompt con titular y bajada, se genera un WEBP y se guarda en `article_hero_images`. El fallo no despublica. `POST /api/v1/admin/articles/{id}/generate-hero?force=true` regenera a mano. El GET público no llama a Replicate.

## Pendiente

Falta `REPLICATE_API_TOKEN` en el entorno (queda vacío en `.env`). Sin eso no hay archivo nuevo ni se puede ver la portada en el frontend. Hay que reconstruir la imagen de `api`/`worker` para que el proceso en marcha tome el código y la dependencia `replicate`. No hay artículos `PUBLISHED` en la base local (6 `DRAFT`).

Prompt real de DeepSeek para el borrador `b8343be8-904f-48b7-b71f-1d4d057fcbd5` (no se guardó imagen):

> A serious editorial illustration in a semi-realistic style, depicting a courthouse interior with a judge's bench, legal documents, and a gavel, symbolizing a judicial investigation. The scene is neutral and muted in color, with no people or recognizable faces. The composition is clean and focused on the legal setting, avoiding any sensationalism. No text, logos, or watermarks. 16:9 aspect ratio.

## Validación

`tests/test_hero_image.py`, `test_registry.py`, `test_public_api.py`, `test_publishing.py`: 38 passed. No se verificó el frontend ni el archivo servido por la API en marcha.
