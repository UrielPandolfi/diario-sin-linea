# Handoff

**Fecha:** 2026-10-03

**Tarea:** Cerrar la comparación real, la vigencia de la reutilización y la actualización de un artículo publicado. Rama `feat/costos-deepseek-cache`, worktree `E:\sin-linea-wt-costos`. Sin merge, push ni despliegue.

## Qué quedó comprobado

El poll de El Ciudadano no se repitió. El ensayo de prompt corto no sirve como validación editorial: pedía un esquema propio y un campo libre, y por eso ambos modelos devolvieron `supported` con certeza alta copiando el texto del claim. En los prompts reales el excerpt sale del paquete de fuentes. Cuando coincide con el claim, esa frase está en el snippet (Derecha Diario; Nube Noticias). No es el claim usado como única prueba.

Auditoría con `article_audit.md` y el snapshot de la versión:

- La Tablada, titular «Murió un joven…». Flash no emitió un issue sobre «joven» y `passed=true`. La auditoría persistida de gpt-4o también había pasado; los LOW son `surface_indeterminate` del código. Una fuente trae «joven» en el título y el cuerpo dice 27 años. La política no bloquea por una palabra aislada.
- Formosa. El bloqueo persistido es `structural_block` (`central_unverified`), igual para cualquier modelo. Flash, sobre el mismo prompt, no marcó HIGH ni MEDIUM por «presunto».
- Marcha `1c28e01f`. Flash reescribió la bajada de la V1 para atribuir («Según la documentación…»). gpt-4o, sobre esa V1 y sobre la V2, pasó sin issues HIGH o MEDIUM. El titular no cambió.
- Enfermero `e6c037d3`. El `structural_block` es de código. gpt-4o no agregó un bloqueo lingüístico.

Juicio, mismo paquete y el mismo prompt de `verification.md`:

- De 7 claims históricos escalados, gpt-4o y `deepseek-v4-pro` coincidieron en 5 status. En dos de La Tablada (vinculación con los disparos; disparo único) gpt-4o dijo `SINGLE_SOURCE` y Pro `SUPPORTED`, porque Pro trató los medios como independientes. Este replay no volvió a admitir esos excerpts en `assess_origins`.
- En el poll, Pro corrió solo en la condena del enfermero y propuso `SUPPORTED` (0.95). gpt-4o, sobre el mismo paquete, dijo `SINGLE_SOURCE` (0.8). La decisión guardada por la política ya es `SINGLE_SOURCE`.
- Los otros tres claims del poll no escalaron. La decisión es de Flash más la política. No hay juicio de Pro ni de gpt-4o ahí. Nano y Flash no devolvieron las mismas relaciones; no se reejecutó `needs_sol_after_assessment`.

Los modelos pedidos coincidieron con los reportados. DeepSeek llevó `thinking={"type":"disabled"}` y no hubo fallback de proveedor en el replay.

Reutilización: TTL de búsqueda 1800 s y de verificación 7200 s. Beat usa 900 s (`INGESTION_POLL_INTERVAL_SECONDS`). Una búsqueda idéntica puede ocultar una página nueva hasta 30 minutos. Si la verificación se reutiliza, no se busca de nuevo hasta 2 horas, y solo cuando el paquete no cambió. Una fuente nueva, una corrección, otro excerpt, otra procedencia, otro modelo o un resultado fallido o incompleto no esperan el TTL. Los tests cubren eso, más el vencimiento, otro `numResults` y la concurrencia.

Actualización: `test_rejected_v2_keeps_published_read_and_approved_v2_publishes_locally` publica una V1 de prueba, rechaza la candidata y comprueba que la lectura pública conserva titular, cuerpo y claims. Después publica la V2 solo en la base de test, sin imagen.

## Gasto en `sin_linea_costos`

Todo calculado. Cero costos desconocidos. Exa del poll está confirmada a USD 0.007 por request.

| Tramo | USD | Llamadas |
| --- | --- | --- |
| Ensayo corto, incluido el corte por esquema inválido | 0.043922640 | 34 |
| Descarte deportivo, solo detección | 0.000883050 | 1 |
| Poll, dos notas | 0.089172062 | 35 |
| Replay de prompts reales, con reintentos de esquema | 0.126329412 | 51 |
| Total | 0.260307164 | 121 |

Quedan USD 2.739692836 de los 3.

Hasta la auditoría aprobada, solo la marcha: USD 0.039793342. No se publicó ni se generó portada, y no hubo otra verificación después de la reescritura. El enfermero se detuvo en `structural_block` a USD 0.049378720; eso no es un costo hasta aprobación.

## Qué activar

Se puede activar, cuando se decida y fuera de este entorno, la caché de búsqueda y la reutilización de verificación. Siguen apagadas. No activar `COST_PROFILE=candidate`, ni la auditoría en Flash, ni el juicio en Pro.

Para volver atrás: `COST_PROFILE=current`, `SEARCH_CACHE_ENABLED=false`, `VERIFICATION_REUSE_ENABLED=false`. `main` y los contenedores `diariosinlnea-*` no se modificaron.

## Pruebas

En `sin_linea_costos_test`: costos, registro, uso, tarifas, Exa, publicación, auditoría, Track B y verificación. La corrida completa de esos módulos pasó; los dos tests nuevos fallaron una vez y, ya corregidos, pasan. No se corrió el resto de la suite.
