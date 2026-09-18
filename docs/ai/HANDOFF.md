# Handoff

**Fecha:** 2026-09-18

**Tarea:** Hacer visible el interruptor de procesamiento automático en Admin.

## Qué quedó

El flag `auto_poll_enabled` ya existía; el control era un botón más en Tablero/Fuentes y no se encontraba. Ahora hay un interruptor fijo en la barra de redacción (`AutoPollToggle` en `AdminShell`): **Procesamiento automático** Activo/Pausado. Pausar no apaga Beat ni el worker: `poll_monitored_sources` no encola. El poll manual sigue.

## Validación

- `npx tsc --noEmit` en `apps/web`: OK
- Compose: rebuild `web` y smoke del interruptor en `/admin`

## Pendiente

Worker y beat no están up en el Compose local de esta sesión (solo api/postgres/redis/web).
