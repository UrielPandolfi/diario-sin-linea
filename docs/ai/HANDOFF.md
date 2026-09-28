# Handoff

**Fecha:** 2026-09-28

**Tarea:** Localidad de interés después del registro, con buscador sobre el catálogo local de GeoRef.

## Resultado

Tras crear la cuenta se pregunta «¿De qué localidad querés estar al tanto?». Se puede continuar con una sugerencia u omitir con «Ahora no». El paso queda en `readers.locality_step` (`pending`, `done`, `skipped`) y no se repite. Quien ya tenía cuenta entra directo y la cambia desde Inicio o Perfil. La preferencia es el id oficial en texto (`interest_locality_id`) y se relaciona con provincia y país en `geo_localities`. Principal usa esa localidad para la cercanía; sin ella, omite el factor. El catálogo se carga una vez con `python -m app.geo.load_localities` (CSV oficial `https://apis.datos.gob.ar/georef/api/v2.0/localidades.csv`, verificado el 2026-09-28). La búsqueda es `GET /api/v1/geo/localities`.

## Verificación

`tests/test_geo_localities.py`: 2 passed. `npm run typecheck` en `apps/web` pasó. En el navegador: registro muestra el paso, la búsqueda ignora mayúsculas y tildes, Aldao distingue departamento, Rosario se guarda y sigue tras cerrar sesión, se puede cambiar y quitar desde Inicio, Perfil permite elegir, «Ahora no» no vuelve a preguntar, y otra cuenta no hereda la preferencia. Una nota publicada sigue abierta sin sesión. El catálogo de la app quedó en 4028 filas; repetir la carga no duplica.

## Pendiente

Sin commit.
