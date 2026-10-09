# Handoff

**Fecha:** 2026-10-09

**Tarea:** Correo transaccional con Resend.

## Hecho

Confirmación de email al registrarse, recuperación de contraseña y aviso al cambiarla salen por la API de Resend, con HTML y texto plano. Los tokens se guardan hasheados. El enlace de recuperación no abre sesión. Las cuentas ya existentes quedan confirmadas en la migración `0024_reader_email_verification` y siguen pudiendo entrar. Una cuenta nueva también entra antes de confirmar el email.

## Validación

`pytest tests/test_transactional_mail.py tests/test_reader_auth.py tests/test_production_prep.py`: 25 passed. No se envió correo real. No se desplegó.

## Configuración que falta

`RESEND_API_KEY` no está en el repo. Los DNS los muestra Resend al agregar `sinlinea.ar` y se cargan en Donweb sin tocar los MX de Zoho. En Railway, solo en la API: `RESEND_API_KEY`, `EMAIL_FROM=no-reply@sinlinea.ar`, `EMAIL_REPLY_TO=contacto@sinlinea.ar`, `APP_BASE_URL=https://www.sinlinea.ar`. Detalle en `docs/ai/correo.md`.
