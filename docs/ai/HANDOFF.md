# Handoff

**Fecha:** 2026-10-09

**Tarea:** Tema oscuro por defecto y login a ancho completo.

## Hecho

Quien entra por primera vez ve el sitio en oscuro. Una preferencia ya guardada no cambia. El ingreso ocupa todo el ancho: el panel izquierdo llega al borde, usa el wordmark y un brillo que sigue el cursor.

## Validación

`lib/theme.test.ts` pasó. En un navegador sin cookies, `/entrar` a ~1920 px tiene `data-theme=dark`, el panel empieza en x=0 y el brillo se desplaza con el puntero.
