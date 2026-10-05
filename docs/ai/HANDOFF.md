# Handoff

**Fecha:** 2026-10-04

**Tarea:** Radar visual en el front. Sin cambios de backend ni de reglas editoriales.

## Qué quedó

La columna «Ahora» y «En vivo» comparten el mismo lenguaje: reloj con segundos, onda de cinco barras, línea vertical con un pulso, barrido horizontal muy tenue, etiqueta `NUEVO` unos 8 segundos cuando entra algo arriba, puntito durante 5 minutos y barra `RADAR ACTIVO`. La edad de «Actualizado hace…» sale de la última respuesta real. No se inventan fuentes.

«Ahora» en el escritorio consulta `/api/v1/now` cada 45 s, igual que «En vivo». El riel muestra solo las 5 últimas y recorta la quinta a la mitad, para que se note que hay más en «En vivo». En el teléfono esa columna está oculta y no consulta hasta abrir la hoja; la hoja sigue mostrando la lista completa.

El inicio ya no tiene las pestañas Principal y Últimas. Siempre ordena como Principal.

## Archivos

`apps/web/features/live/radar.ts`, `radar-chrome.tsx`, `now-panel.tsx`, `live-timeline.tsx`, `apps/web/features/shell/home-rail.tsx`, `apps/web/app/(public)/en-vivo/page.tsx`, `apps/web/app/globals.css`.

## Validación

`npm test` en `apps/web` pasó. Con la API arriba y sin beat, el inicio queda en el orden principal, el riel recorta la quinta nota y En vivo lista las publicadas.
