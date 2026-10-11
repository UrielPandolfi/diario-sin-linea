# Handoff

**Fecha:** 2026-10-11

**Tarea:** Reemplazar el logo viejo de líneas cortadas por el wordmark y enlazarlo al inicio.

## Hecho

En Cómo funciona el encabezado usaba `BrandMark` y volvía a `/como-funciona`. Ahora usa el wordmark (`sl-logo`) y va a `/`. El mismo reemplazo está en el paso de localidad. Se borraron `brand-mark.tsx` y `public/mark.svg`.

## Validación

En local, el encabezado de `/como-funciona` muestra el wordmark y el clic llega a `/`. En `/onboarding` el logo es el mismo y también va a `/`. En celular el encabezado entra en 390 px.
