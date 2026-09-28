# Handoff

**Fecha:** 2026-09-28

**Tarea:** Inicio autenticado con Principal y Últimas. Sin commit.

## Resultado

Principal rankea relevancia, actualidad y cercanía, y suma afinidad por `event_type` con lecturas y Me gusta. Últimas ordena por la primera publicación. Sin sesión, el feed web redirige a `/entrar`. La nota publicada sigue abierta.

## Verificación

`tests/test_home_feed.py`: 4 passed en Postgres de Compose (`sin_linea_test`). Frontend: `npm test` 59 ok, lint y typecheck ok. En `next dev`, sin cookie, `/?vista=ultimas` va a `/entrar` y el enlace a registro conserva ese destino. El bundle de Inicio trae Principal y Últimas.

No se reejecutó el resto de pytest: un contenedor posterior no resolvió el host `postgres`.

## Pendiente

Aplicar `0018_reader_signals` en la base de la app. `editorial_topic` no está en el suceso; la afinidad usa `event_type`. Guardados y Poneme al día no se implementaron.
