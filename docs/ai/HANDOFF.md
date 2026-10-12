# Handoff

**Fecha:** 2026-10-11

**Tarea:** Plausible en el frontend, solo visitas de página.

## Hecho

El layout raíz carga el snippet una vez, y solo si `NODE_ENV` y `VERCEL_ENV` son `production` y el host es `sinlinea.ar` o `www.sinlinea.ar`. El tracker registra la carga y la navegación interna. `transformRequest` descarta lo que no es pageview, `/admin`, query, hash, propiedades y el token de `/seguimiento`. No hay variable nueva. `/privacidad` deja de decir que no hay analítica.

## Validación

En `apps/web`: `npm test` 81 passed, `npm run typecheck`, `npm run lint` y `npm run build` ok. Con `next start` local el HTML no incluye el script, tampoco si el host reenviado es `www.sinlinea.ar`. Con `VERCEL_ENV=production`, el snippet aparece una vez en `sinlinea.ar` y `www.sinlinea.ar`, y no en `sinlinea.com.ar`, preview ni localhost. En el navegador, `/privacidad` muestra el párrafo nuevo y una navegación a esa página no pide `plausible.io`.

## Pendiente

Confirmar en Plausible que el dominio del sitio es `sinlinea.ar` o `www.sinlinea.ar`. Si quedó `sinlinea.com.ar`, las visitas no aparecen. Tras el deploy, revisar un solo `plausible.init`, el POST a `/api/event` al cambiar de página pública y la ausencia del POST en `/admin`.
