# Handoff

**Fecha:** 2026-10-02

**Tarea:** Preparar el sitio para producción sin desplegarlo: admin, Next 15.5.27, cuenta, textos legales, ocultar funciones inexistentes, Guardados, «Ahora» y etiquetas de fuente.

## Resultado

La contraseña de admin ya no tiene fallback de desarrollo. Vive solo en `.env` (gitignored) para Compose local; producción no se tocó. Las páginas `/admin` consultan `/api/v1/admin/me` y la sesión guarda un sello de la contraseña vigente. Next quedó en 15.5.27 y React en 19.0.8. Recuperar y cambiar contraseña están cableados; sin SMTP la API no afirma un envío. Privacidad y Términos son públicos y no inventan la identidad legal. Seguir, Comentar, mapas, Seguidos y Notificaciones salieron de la interfaz. Guardados se abre desde Perfil. Una republicación sin cambio de texto no vuelve a «Ahora»; si el texto cambia, la entrada dice qué cambió y apunta al mismo artículo. Las etiquetas públicas limpian prefijos de host y omiten títulos ilegibles, sin alterar la URL guardada. Las portadas de IA no se modificaron.

## Verificación

API reconstruida: `test_production_prep.py` y `test_reader_auth.py` 16 passed sobre la imagen nueva. Antes, en la imagen anterior con el código montado: `test_admin.py`, `test_saved.py`, `test_publishing.py`, `test_public_api.py` y `test_cases.py` pasaron. Web: `npm test` 60, `tsc --noEmit`, `next lint` y `next build` (Next 15.5.27). El contenedor web ejecuta `npm start` / `next-server` 15.5.27. Alembic local en `0021_account_security`. `dev-admin` responde 401 y la contraseña nueva 200. `/dev/respaldo` responde 404. `/admin` redirige a `/admin/login`. `auto_poll_enabled` está apagado y el proceso local tiene `AUTO_PUBLISH` en false. `pg_dump` custom del Postgres local se listó y se borró; no se restauró encima de la base.

## Pendiente

No hay commit ni despliegue. Producción no se modificó. Faltan SMTP, `COOKIE_SECURE=true`, `SITE_URL` HTTPS, un `APP_SECRET` que no sea el de ejemplo y la identidad legal del responsable.
