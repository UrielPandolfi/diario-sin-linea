# Handoff

**Fecha:** 2026-09-17

**Tarea:** Punto 7 — SEO + Open Graph + compartir. Cerrado.

## Validación 2026-09-17

Web Compose reconstruida (imagen nueva en `:3000`). Suite API: 638 passed. `npm test` 11 passed; lint/typecheck/build OK. Smoke contra el contenedor: `/` y `/en-vivo` 200 sin cookie; `/buscar` `noindex, follow`; `/local` selector sin pulse infinito; artículo publicado con canonical/OG/Twitter/JSON-LD en `SITE_URL`; `public_id` 308 al slug; sitemap solo público; robots sin `Disallow: /buscar`; draft y `READY_FOR_REVIEW` 404 y ausentes del sitemap; admin/entrar/onboarding `noindex`. `getSiteUrl()` lee `SITE_URL`; Host/`X-Forwarded-Host`/`API_URL` no lo reemplazan.

## Veredicto

El origen público es `SITE_URL`. Las noticias publicadas tienen metadata server-side, canonical absoluto, Open Graph/Twitter, JSON-LD `NewsArticle` y entran al sitemap. Drafts y `READY_FOR_REVIEW` sin live no. `/` y `/en-vivo` se rastrean sin cookie de localidad. `/buscar` es `noindex, follow` y no está en `Disallow`. Un `public_id` en la URL redirige 308 al slug. Preview (`VERCEL_ENV` ≠ production) envía `noindex, nofollow`.

## Tests

- `apps/web`: `npm test` (`lib/seo/seo.test.ts`).
- `apps/api/tests/test_sitemap_articles.py`: publicado entra; draft, READY sin live y archivado no.
- `apps/api/tests/test_domain.py`: `update_content` conserva el slug.

## Smoke manual

1. `/` sin cookie: feed nacional.
2. Noticia publicada: titular/summary en `<head>`, canonical, OG, Twitter, JSON-LD.
3. `/sitemap.xml` y `/robots.txt` (sitemap absoluto; `/buscar` no en Disallow).
4. Draft: 404 y ausente del sitemap.
5. Compartir: Web Share en mobile; «Enlace copiado» en desktop.
6. `/noticias/{public_id}` → 308 al slug.
7. Tras deploy: Search Console + validadores de preview/structured data (no es CI).
