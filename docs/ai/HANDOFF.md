# Handoff

**Fecha:** 2026-10-11

**Tarea:** El selector de localidad en el registro no devolvía Rosario en producción.

## Hecho

La web y la API ya hablaban: `GET /api/v1/geo/localities` respondía 200 con `{"items":[]}`. `geo_localities` tenía 0 filas porque el deploy no corre la carga. Se ejecutó `python -m app.geo.load_localities` en la API de producción: 4028 filas. `ros` incluye Rosario (Santa Fe).

## Validación

Conteo en la base de producción y `search_localities("ros")` desde el servicio de la API. No hay cambio de código ni tests nuevos.
