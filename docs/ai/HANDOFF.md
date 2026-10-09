# Handoff

**Fecha:** 2026-10-09

**Tarea:** Cortar el bucle entre inicio e ingreso cuando la base ya no tiene al lector.

## Hecho

La cookie `sl_reader` se firmaba en el navegador y el middleware la daba por válida aunque el lector no existiera. `/` cargaba, el feed respondía 401 y mandaba a `/entrar`; `/entrar` veía la cookie y volvía a `/`. Ahora la web pregunta `GET /api/v1/auth/session` en las rutas con sesión y, si el lector no está, borra la cookie y deja el ingreso. La API también borra esa cookie en `/session` y en el 401 de una ruta que la exigía.

## Validación

Tests de `reader-gate` en la web y `test_deleted_reader_drops_the_signed_cookie` en la API. Producción no se desplegó: el bucle sigue en https://www.sinlinea.ar hasta publicar web y API. Mientras tanto, borrar las cookies de ese sitio corta el ciclo.
