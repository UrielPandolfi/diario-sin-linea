# Handoff

**Fecha:** 2026-09-18

**Tarea:** Merge a `main` del interruptor de procesamiento automático y el resto de la rama.

## Qué quedó

El flag `auto_poll_enabled` ya existía; el control era un botón más en Tablero/Fuentes y no se encontraba. Ahora hay un interruptor fijo en la barra de redacción (`AutoPollToggle` en `AdminShell`): **Procesamiento automático** Activo/Pausado. Pausar no apaga Beat ni el worker: `poll_monitored_sources` no encola. El poll manual sigue.

`Settings` reescribe `postgres://` y `postgresql://` a `postgresql+psycopg://` (Railway).

## Validación

- `npx tsc --noEmit` en `apps/web`: OK
- Compose: rebuild `web` y smoke del interruptor en `/admin`

## Pendiente

Redeploy de Vercel Production (`main`) y de API/worker/beat en Railway para que el interruptor y `PATCH /api/v1/admin/ingestion` existan en producción.
