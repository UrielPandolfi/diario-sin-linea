# Handoff

**Fecha:** 2026-09-28

**Tarea:** Guardados privados por lector. Sin commit.

## Resultado

Cada lector guarda o quita una noticia publicada. La relación queda en `reader_event_saves` con `saved_at`. `/guardados` lista la versión publicada, de la más reciente a la más antigua. Sin sesión, la ruta va a `/entrar`; en una nota pública el botón invita a iniciar sesión.

## Verificación

`tests/test_saved.py`: 2 passed en Postgres de Compose (`sin_linea_test`). Cubren sesión, borrador oculto, idempotencia, orden por `saved_at`, paginación, otra sesión del mismo lector, aislamiento entre usuarios y exclusión al archivar. Frontend: lint y typecheck ok.

En el navegador, con la API local: sin sesión, Guardar en la nota lleva a `/entrar` y conserva la lectura; con sesión, guardar y quitar funciona en la nota, en la card de Inicio y en `/guardados`. El vacío dice “Todavía no guardaste noticias”. Un fallo simulado muestra “No se pudo quitar.” y deja el botón en Guardado.

No se reejecutó el resto de pytest.

## Pendiente

Aplicar nada pendiente de esta tarea en la base local: al levantar la API se corrieron `0017_readers`, `0018_reader_signals` y `0019_reader_saves` sobre `sin_linea`. `/seguidos`, `/notificaciones` y Poneme al día siguen sin implementar.
