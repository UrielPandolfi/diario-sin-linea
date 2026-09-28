# Handoff

**Fecha:** 2026-09-28

**Tarea:** El inicio y las áreas personales piden sesión. Las noticias publicadas se leen sin cuenta, con invitación inferior para visitantes. Sin commit.

## Resultado

No había cuentas de lectores: `/entrar` era la localidad y el admin usa otra cookie. Se agregó sesión real con email y contraseña (`readers`, cookie httpOnly `sl_reader`), sin OAuth ni correo. `GET /api/v1/feed` exige esa sesión. El artículo publicado sigue público.

## Verificación

Frontend: `npm test` 58 ok, lint sin avisos, typecheck ok. En `next dev`, sin cookie, `/` y `/?vista=` redirigen a `/entrar`; `/perfil`, `/guardados`, `/seguidos` y `/notificaciones` también. `/buscar`, `/local`, `/en-vivo`, `/como-funciona`, `/onboarding` y `/mark.svg` responden 200. Un `next` externo se reescribe a `/`. Una cookie firmada abre `/` sin redirigir. La invitación se vio en claro/oscuro y en móvil, se cierra y no vuelve en la misma pestaña; el panel de respaldo queda por encima.

Pytest de la API no corrió: `.env` no tiene `TEST_DATABASE_URL` y Postgres local no aceptó conexión. El login completo contra la API tampoco: el proceso en `:8000` no está.

## Pendiente

Recuperación de acceso y verificación por email no existen. Me gusta, Guardados y Poneme al día siguen sin implementarse; las rutas personales solo piden sesión.
