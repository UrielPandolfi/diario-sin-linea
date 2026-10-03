# Handoff

**Fecha:** 2026-10-03

**Tarea:** Perfil DeepSeek y reutilización de búsquedas/verificaciones, en rama y base aisladas.

## Resultado

Rama `feat/costos-deepseek-cache`, worktree `E:\sin-linea-wt-costos`. No hay merge ni push. Flags apagados: `COST_PROFILE=current`, `SEARCH_CACHE_ENABLED=false`, `VERIFICATION_REUSE_ENABLED=false`.

Para volver atrás alcanza con dejar esos tres valores. No hace falta revertir el código para conservar el comportamiento anterior.

Ensayo A–D sobre dos sucesos congelados (Formosa `a614745e`, La Tablada `58759b17`), sin Exa, sin portada y sin publicación. Esta corrida gastó USD 0.0242 (A 0.0208 en 8 llamadas, C 0.0034 en 8, B y D 0 porque reutilizan). Una corrida anterior, cortada por un esquema inválido, sumó cerca de USD 0.020. Total del ensayo real, menos de USD 0.05, dentro del tope de USD 3. No es el ledger histórico de USD 1.72.

En ese prompt corto, gpt-4o y `deepseek-flash` rechazaron el titular de Formosa por motivos distintos. gpt-4o aceptó el de La Tablada; flash lo rechazó por llamar «joven» a una persona de 27 años. No hay equivalencia editorial. El juicio compacto de ambos modelos respondió `supported` / `high` y no citó un fragmento distinto del texto del claim.

Poll aislado de `https://www.elciudadanoweb.com/feed`, perfil candidato, caché fría, `AUTO_PUBLISH=false`, sin Beat y sin portadas. Dos notas:

- Enfermero, `e6c037d3`: USD 0.049 en 17 llamadas. Auditoría `structural_block`. Artículo `DRAFT`, `published_version` null.
- Marcha del Orgullo, `1c28e01f`: USD 0.040 en 18 llamadas. Auditoría `passed` tras una reescritura con `gpt-5.6-luna`. Artículo `READY_FOR_REVIEW`, `published_version` null, `current_version` 2.

La búsqueda (USD 0.007 estimados por request) es la mayor parte. El juicio `deepseek-v4-pro` corrió solo cuando la verificación escaló (USD 0.0045 en la primera nota). `thinking` salió `{"type":"disabled"}` y `reasoning_tokens` 0. Dos ítems deportivos del feed fueron descartados por el gate, como antes.

## Cómo probarlo

`docker compose -f docker-compose.costos.yml -p sin-linea-costos up -d postgres redis` y apuntar `DATABASE_URL` a `sin_linea_costos` en el puerto 55432. Pytest usa `sin_linea_costos_test`. No usar la base `sin_linea`.

Tests de esta sesión: `test_cost_optimization.py`, `test_registry.py`, `test_llm_usage.py`, `test_llm_costs.py`, `test_exa.py`, `test_publishing.py` — 58 passed. No es la suite entera.

## Pendiente

No activar la auditoría en `deepseek-flash` hasta revisar desacuerdos como el de «joven». El juicio `deepseek-v4-pro` tiene una sola nota real. La muestra no cubre actualizaciones ni el ledger de septiembre. Docker no está en Windows; el Compose aislado corre por el Docker de WSL.
