# Handoff

**Fecha:** 2026-09-22

**Tarea:** Rediseño del frontend público (light por defecto, Newsreader, panel de respaldo lateral). Rama `frontend/public-editorial-redesign` desde `main`/`track-c` @ `83c2fd8`. Sin commit, sin deploy.

## Resultado

El frontend público usa paleta marfil/verde, Newsreader + Inter, tema **claro por defecto** (cookie `sl_theme` + `localStorage` `sl-theme`), y el DTO C9 vigente en un popover lateral (≥1280 + puntero fino) o bottom sheet. No se tocó Verification/Claims/Writing/Audit/Publish.

## Cómo abrir

API en `:8000`. Web de este cambio: `cd apps/web && npx next dev -p 3002` (el Compose en `:3000` no incluye este árbol). QA de claims: `/dev/respaldo`.

## Validación

`apps/web`: lint, typecheck, build y 53 tests (tema, hover/teclado/sheet, cambio de claim). Visual en `localhost:3002`: artículo 1440 light/dark con panel, sheet ~390, feed 768 y 1440, buscar persistiendo dark. Capturas en `e:\temp\cursor\screenshots\`: `article-desktop-1440-light.png`, `article-claim-panel-1440.png`, `article-dark-claim-panel.png`, `article-mobile-sheet.png`, `home-768.png`, `home-1440.png`, `buscar-1440-dark.png`.

## Limitaciones

No hay rubro editorial: kicker/breadcrumb usan localidad/provincia. Guardados/Seguidos/Notificaciones siguen siendo stubs. El admin comparte tokens y fuentes; no se rediseñó. El overlay «1 Issue» es de Next en el browser de Cursor. En Chromium, el `<button>` del claim no pinta el resalte línea por línea (`box-decoration-break`) y queda como bloque. 1920 no se capturó aparte: a 1440 el artículo ya usa el ancho máximo de lectura.
