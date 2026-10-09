# Handoff

**Fecha:** 2026-10-09

**Tarea:** Líneas de luz en el ingreso y brillo mapeado a toda la ventana.

## Hecho

En `/entrar` y `/registro`, el panel izquierdo tiene líneas horizontales leves (teal y ocre). El brillo y el punto brillante de esas líneas usan la posición del cursor en toda la ventana, proyectada sobre el panel: arriba a la derecha de la pantalla queda arriba a la derecha del panel; el centro de la pantalla, en el centro del panel.

## Validación

En un navegador sin cookies, a 1920×1080, el panel empieza en x=0. Con el puntero en (1910, 8) el brillo quedó en ~99% / 1% del panel; en el centro de la ventana, en ~50% / 50%.
