# Handoff

**Fecha:** 2026-10-09

**Tarea:** Reordenar la barra lateral: perfil abajo y menú «Más».

## Hecho

En la barra, Perfil quedó al final (debajo de Salir). En el lugar que ocupaba hay tres puntos («Más»). El panel abre Transparencia, Cómo funciona y Contacto, cada uno con icono y texto.

## Validación

`tsc --noEmit` en `apps/web` pasó. En el navegador, a 959 px y a 1280 px, el panel muestra las tres entradas y recibe el clic. El front sigue en `next dev` (http://localhost:3000); la API, Postgres, Redis y el worker están arriba, sin Beat.
