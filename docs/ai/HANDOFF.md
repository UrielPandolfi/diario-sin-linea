# Handoff

**Fecha:** 2026-10-09

**Tarea:** Mostrar la recuperación de contraseña en la pantalla de ingreso.

## Hecho

`/cuenta/recuperar`, `/cuenta/restablecer` y `/cuenta/verificar` salieron del layout público. Comparten el panel de `/entrar` y no muestran la barra lateral, aunque haya sesión.

## Validación

En local, con sesión: `/cuenta/recuperar` a 1440×900 no tiene `aside` ni `sl-shell`; el formulario avisa si el pedido no sale. `/cuenta/restablecer` y `/cuenta/verificar` usan el mismo panel. `/contacto` sigue con la barra. Sin cookie, `/entrar` y `/cuenta/recuperar` responden 200 con `sl-auth-stage`. Producción no se desplegó.
