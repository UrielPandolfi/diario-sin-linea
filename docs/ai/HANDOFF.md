# Handoff

**Fecha:** 2026-10-02

**Tarea:** Borradores no aprobados en Transparencia y un pulido visual del sitio público.

## Resultado

«Borradores no aprobados» está en Perfil → Transparencia (`/transparencia/borradores`). La API es `GET /api/v1/transparency/rejected-drafts`, solo con sesión de lector, `Cache-Control: private, no-store` y `X-Robots-Tag: noindex`. Cada fila es la candidata vigente con texto completo y la auditoría concluida que impide aprobarla.

El sitio conserva la estética editorial. Se sumaron tarjetas, color en etiquetas y animaciones cortas. El activo de la navegación vuelve al gris cálido, sin barra de acento. Las animaciones respetan `prefers-reduced-motion`.

## Pendiente

Worker y beat no formaron parte de la corrida local de visualización. Las estadísticas de Transparencia no están.
