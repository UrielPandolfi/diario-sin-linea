# Evaluación de deduplicación — 2026-09-14

**Veredicto: DEDUP NO APTO PARA MVP.** Se reprodujeron dos fusiones de sucesos distintos en el caso C. No se modificó código de producto, thresholds, providers, prompts ni schemas. El arreglo de `event_type` permanece cerrado.

## Método y límites

Se ejecutó `DetectionService.detect()` completo, con ingesta real de Sources/SourceItems, repositorios reales, PostgreSQL/pgvector y commit después de cada procesamiento. Base temporal `sin_linea_dedup_test_d021dc323d`, separada de la base viva; se elimina después de exportar la evidencia. No se ejecutan workers ni etapas posteriores.

Interferencia comprobada: con candidatos fieles de accidentes comunes y el gate original, **A/B/C producen 0 Events y 0 EventSources**, con 2 Sources y 2 SourceItems `SKIPPED`, razón `NOT_PUBLIC_AFFAIRS`. No llegan a dedup. Se agregaron tres tests para documentarlo. No es un fallo de matching, sino una limitación del uso de estos ejemplos en el pipeline editorial actual.

Para los tests exclusivos de dedup se reemplaza **solo en el test** el resultado allowed/reason del gate, después de ejecutar su normalización real. No se inventan atributos políticos para hacer pasar accidentes. Los candidatos conservan `editorial_topic=ACCIDENT`, `is_public_affairs=false`, el texto del caso como `what_happened`/resumen, `event_type=accidente`, ciudad Rosario y provincia Santa Fe. No se sustituye ninguna decisión de dedup ni el resultado de consultas a repositorios.

Los dos textos, Sources, SourceItems, hashes, URLs y dominios son distintos: `https://source-0.test/{caso}` y `https://source-1.test/{caso}`. Primera detección sin candidatos: crea E1 con `no_candidates`. E1/E2 son alias para facilitar la lectura; los UUID reales y las filas persistidas están en las trazas.

Extractor: `FakeStructuredLLM` existente. Terra: otro `FakeStructuredLLM`, con respuesta explícita solo para la zona ambigua. Embeddings: instancia del fake existente con dos vectores unitarios distintos, rellenados con ceros hasta 1024 dimensiones: `vA=(1,0,…)`, `vB=(s,sqrt(1-s²),…)`. El coseno real calculado por el servicio es `s`. No hay sentinelas en el texto, similitud 1 artificial ni cambios de thresholds. Los valores 0.65/0.80/0.94 prueban rangos concretos; **no son mediciones de Voyage ni una calibración de su calidad semántica**. La variante de C por Level 1 falla independientemente de esos valores.

A/D usan el lunes 14/09/2026 y 15:00 -03 como hora representativa de «por la tarde», sin pretender que sea una hora exacta extraída. B conserva `occurred_at=null` porque los textos no dan fecha/hora. C conserva las horas explícitas 14:00 y 18:00 -03 y la fecha común del escenario. Todos los Events se detectan durante la prueba, dentro de la ventana configurada.

## Arquitectura actual del dedup

`SourceItem → extracción → gate editorial → _resolve_event → persistencia de entidades/embedding → PROCESSED + PipelineRun SUCCESS`.

1. Un SourceItem ya vinculado y no PENDING devuelve `already_linked` antes de extraer.
2. Se busca `canonical_url or url` en los SourceItems ya vinculados. Coincidencia: `level1_url`; no aplica ventana temporal.
3. Se recuperan hasta 40 Events recientes por `detected_at`, tipo y localidad; si el conjunto está vacío, se repite sin tipo/localidad.
4. Level 1 compara día, tipo, localidad y nombres de entidades. Coincidencia: `level1_code`.
5. Si no coincide, se obtiene embedding del candidato, se recuperan los vectores de los Events y se calcula coseno en Python. Vectores faltantes se generan con texto de tipo/título/resumen y se guardan.
6. Mejor score alto: vincula directamente (`embedding_high:s`). Mejor score ambiguo: envía hasta cinco Events a Terra; vincula por `terra_existing` o crea por `terra_new`. Score bajo: crea (`embedding_low:s`). Sin Events puntuados: crea (`no_candidates`).
7. Crear genera un Event y su vínculo INITIAL/primario. Vincular agrega CONFIRMING/no primario. El servicio persiste entidades, pero conserva el embedding existente y el título/resumen originales del Event.

Código inspeccionado: [DetectionService](../../apps/api/app/services/detection_service.py), [EventRepository](../../apps/api/app/repositories/core.py), [EventService](../../apps/api/app/services/event_service.py), [prompt de Terra](../../apps/api/app/prompts/deduplication.md).

## Thresholds y reglas actuales

Valores efectivos al cargar `.env` con `Settings`; los tests recibieron los mismos valores:

| Configuración | Valor |
| --- | --- |
| EVENT_MATCH_HIGH_THRESHOLD | 0.88 |
| EVENT_MATCH_LOW_THRESHOLD | 0.72 |
| EVENT_MATCH_WINDOW_HOURS | 72 |
| Embedding configurado | Voyage `voyage-3`, 1024 dimensiones |
| Rol AMBIGUOUS_DEDUP, llamado «Terra» en código | OpenAI `gpt-4o-mini` |

No hubo llamadas pagas a esos modelos en esta evaluación.

- Ramas: `s ≥ 0.88` fusiona; `0.72 ≤ s < 0.88` consulta Terra; `s < 0.72` crea.
- Ventana de **detección**, no distancia entre fechas del suceso. Un hecho antiguo detectado hoy entra; un Event detectado hace más de 72 h sale aunque otra publicación lo amplíe hoy. URL elude esa ventana.
- Consulta inicial: igualdad exacta de strings de tipo/localidad, si están presentes; excluye del filtro de tipo solo vacío/`unknown`. Límite 40, orden por detección descendente. No filtra provincia, país, dirección ni estado del Event. Si devuelve al menos uno, no amplía la búsqueda al resto.
- Level 1 exige `occurred_at`, tipo distinto de vacío/`unknown`, localidad y alguna entidad. Compara `.date()` del candidato y `started_at` del Event sin normalización explícita de zona horaria; no compara horas. Exige tipo igual, localidad plegada igual y **al menos dos nombres normalizados compartidos**.
- Para ese solapamiento cuentan todos los nombres, incluidos PLACE; no pondera tipo/rol de entidad ni su poder identificador. No compara vehículos, esquina, dirección, provincia o contradicciones del texto. Elige la primera coincidencia.
- El texto del embedding incluye tipo, `what_happened`, resumen, ciudad, provincia y nombres de entidades. No incorpora `occurred_at`, dirección ni país como campos independientes; solo aparecen si también están escritos en los otros campos.
- La rama alta no exige igualdad de fecha, hora, dirección o entidades; tampoco vuelve a validar tipo/localidad tras el fallback global de recuperación.
- Terra recibe los cinco mejores del conjunto recuperado; no necesariamente todos superan low. `confidence` no condiciona el resultado. `EXISTING_EVENT` con UUID inexistente o sin UUID termina en nuevo Event; con UUID existente se consulta por ID, sin verificar pertenencia a los candidatos enviados.

## Tests que ya existían

Antes de agregar tests se ejecutaron `test_detection.py`, `test_prompt_payloads.py` y `test_publication_outcome.py`: **50 passed, 1 warning** (15.40 s).

| Test existente | Cobertura efectiva / hueco |
| --- | --- |
| `test_new_item_creates_event` | Creación; no compara publicaciones. Usa candidato controlado de gobierno aunque el SourceItem diga choque. |
| `test_same_url_links_without_creating_another_event` | Evita duplicado por URL; no prueba URLs distintas. |
| `test_same_url_relink_skips_duplicate_entity_roles` | Fuentes distintas con URL igual y persistencia de roles; no prueba A semántico. |
| `test_content_update_of_same_item_does_not_create_another_event` | Actualiza el mismo SourceItem; no cubre B con otro SourceItem/Source. |
| `test_same_day_type_locality_without_strong_overlap_does_not_merge` | Aproxima C con dos incendios, sin entidades. Fake por defecto asigna vectores ortogonales a textos distintos: no prueba similitud alta ni dos entidades compartidas. |
| `test_entities_are_not_merged_across_events` | Un nombre compartido no fuerza Level 1; verifica separación de entidades con similitud baja. |
| `test_pellegrini_crash_is_skipped` y otros de gate | Accidentes comunes quedan fuera antes de dedup. |
| `test_terra_dump_omits_editorial_fields` | Serializa el candidato; no ejecuta `_ask_terra`, captura payload real ni prueba decisiones. |
| `test_normalize_embedding_score_prefix`, `test_terra_new_is_created` | Presentación de códigos/metadata; no ejecutan dedup. |

No había cobertura completa de A/B con fuentes y URLs distintas, Level 1 positivo, embedding alto ni D con las dos decisiones de Terra.

## Caso A — mismo suceso, redacción diferente

SourceItems: los dos textos solicitados, sin igualarlos ni sustituir sus URLs. Candidatos: accidente de colectivo/auto, seis heridos, mismo lunes por la tarde; nombres de lugar `Pellegrini` y `Corrientes` en ambos.

`Item A → candidato A → [] (consulta filtrada y fallback) → Level 1 sin match → sin scores → sin Terra → no_candidates → crea E1`.

`Item B → candidato B → [E1] por accidente/Rosario/72h → dos lugares compartidos y mismo día → level1_code → embedding no comparado → sin Terra → vincula E1`.

**Resultado: 2 Sources, 2 SourceItems PROCESSED, 1 Event, 2 EventSources; segundo created=false y mismo event_id.** Solo se generó el vector de E1 para almacenarlo; no se calculó similitud para B. No fue un match por URL.

Variante sin entidades extraídas: Level 1 no coincide, coseno controlado 0.94, `embedding_high:0.940`, mismo resultado y cero llamadas a Terra. Verifica la rama alta sin inventar dos entidades para forzar Level 1.

## Caso B — información adicional

Candidatos fieles: dos colectivos chocaron / seis heridos en ese choque; `occurred_at=null` en ambos. Los lugares son los mismos.

`Item A → candidato A → [] → sin Level 1 ni scores → no_candidates → E1`.

`Item B → candidato B → [E1] → Level 1 no aplicable por fecha ausente → coseno 0.94 → sin Terra → embedding_high:0.940 → vincula E1`.

**Resultado: 2 Sources, 2 SourceItems, 1 Event, 2 EventSources; segundo created=false.** Se verificó persistencia del vínculo. El dato de seis heridos queda en SourceItem B; el resumen del Event sigue siendo el de A y su embedding no se regenera. Eso no cambia la identidad del Event ni implica que se haya actualizado el artículo; no se ejecutaron etapas posteriores.

## Caso C — hechos distintos

Candidatos: accidente/Rosario/Santa Fe en el mismo día. A: colectivo-auto, Pellegrini/Corrientes, 14:00. B: colectivo-moto, Pellegrini/Oroño, 18:00. Ninguna diferencia se elimina del texto ni de los campos temporales/dirección.

En las tres variantes, A crea E1; B recupera `[E1]` por tipo/localidad/ventana.

| Variante | Level 1 | Similitud evaluada | Terra | Decisión B | Events / SourceItems / EventSources |
| --- | --- | --- | --- | --- | --- |
| Entidades: calles; solo Pellegrini compartida, s=0.65 | No coincide | 0.65 | No | `embedding_low:0.650`, crea E2 | **2 / 2 / 2**, correcto |
| Mismas entidades, s=0.94 | No coincide | 0.94 | No | `embedding_high:0.940`, vincula E1 | **1 / 2 / 2**, incorrecto |
| Cada candidato también incluye Rosario como PLACE; s=0.65 | Coincide por Rosario + Pellegrini | No se calcula | No | `level1_code`, vincula E1 | **1 / 2 / 2**, incorrecto |

La ciudad proviene del contexto explícito del escenario. Los tipos/roles de estas entidades son PLACE/lugar, sin alterar el código de entidades. La tercera variante evidencia que una extracción válida puede producir una fusión incorrecta incluso antes de usar embeddings. No depende de demostrar que Voyage devuelva 0.94.

## Caso D — similitud ambigua

A: «Un colectivo chocó contra un auto en avenida Pellegrini durante la tarde del lunes.» B: «Una colisión entre un ómnibus y un vehículo dejó heridos en el centro de Rosario el lunes por la tarde.» B carece de esquina/vehículo exacto suficientes para resolver identidad; no se impone una verdad de identidad al fake.

`A → candidato A → [] → no_candidates → E1`.

`B → candidato B → [E1] → Level 1 sin dos nombres compartidos → coseno 0.80 ∈ [0.72,0.88) → Terra una vez → respuesta controlada → persistencia`.

Se ejecutó el mismo caso dos veces en bases de tests limpias:

- `EXISTING_EVENT`, ID E1, confidence 0.9: **1 Event, 2 SourceItems, 2 EventSources**, `terra_existing`, segundo created=false.
- `NEW_EVENT`, event_id null, confidence 0.9: **2 Events, 2 SourceItems, 2 EventSources**, `terra_new`, segundo created=true.

Prueba el enrutamiento y la persistencia de ambas decisiones, no la calidad del modelo real. A por Level 1, A/B por embedding alto y C bajo registran cero llamadas a Terra.

Payload real capturado en la corrida final de EXISTING_EVENT:

```text
Candidato: {"event_type":"accidente","what_happened":"Una colisión entre un ómnibus y un vehículo dejó heridos en el centro de Rosario el lunes por la tarde.","occurred_at":"2026-09-14T15:00:00-03:00","province":"Santa Fe","locality":"Rosario","neighborhood":null,"address_text":null,"entities":[{"name":"Rosario","entity_type":"PLACE","role":"lugar"}],"short_summary":"Una colisión entre un ómnibus y un vehículo dejó heridos en el centro de Rosario el lunes por la tarde."}
Eventos existentes:
- id=a9b8cf34-73b0-498f-9552-e1d930b03f10 type=accidente score=0.800 title=Un colectivo chocó contra un auto en avenida Pellegrini durante la tarde del lunes. place=Rosario summary=Un colectivo chocó contra un auto en avenida Pellegrini durante la tarde del lunes.
```

El system prompt es `deduplication.md`, sin cambios: exige mismo suceso y `NEW_EVENT` ante duda razonable. El test compara exactamente los campos enviados y la línea existente. El candidato incluye tiempo, dirección y entidades; **la línea de E1 no incluye sus campos estructurados `started_at`, dirección, provincia ni entidades**. Solo se conocen si casualmente aparecen en título/resumen. Se envía score aunque el system prompt diga que no use embeddings.

## Nuevos tests y resultados

Único archivo nuevo de tests: [test_detection_dedup.py](../../apps/api/tests/test_detection_dedup.py), **11 casos** (parametrizados): tres para la interferencia del gate, dos para A, uno para B, tres para C y dos para D. Reutiliza fakes, servicios y fixture de DB existentes; observadores de métodos delegan al código real. Las trazas se exportan mediante `record_property`/JUnit de pytest, sin framework nuevo.

Primera ejecución: **9 passed, 2 failed** (9.28 s). Se conservaron las exigencias de dos Events en los fallos; no se marcaron xfail ni se cambió código de producto.

Corrida final, desde `apps/api`, con `DATABASE_URL` a la base temporal:

```bash
python -m pytest tests/test_detection.py tests/test_detection_dedup.py tests/test_prompt_payloads.py tests/test_publication_outcome.py -q --tb=short -o junit_family=legacy --junitxml <ruta-de-evidencia>/final-run.xml
```

**59 passed, 2 failed, 1 warning in 20.36s; exit code 1.** Warning preexistente de Alembic por `path_separator`. Fallos:

- `test_case_c_different_crashes_must_not_merge[high_similarity]`: Events real=1, esperado=2.
- `test_case_c_shared_city_and_avenue_must_not_override_conflicts`: Events real=1, esperado=2.

Evidencia local, fuera de Git: `.editorial-evals/dedup-20260914/`. `baseline.txt`, `first-run.txt/xml`, `final-run.txt/xml`, `traces.json`, `file-hashes.json`, `environment.json`. Las 11 trazas contienen inputs, candidatos, filtros e IDs recuperados, Level 1, scores, payloads/respuestas de Terra, conteos, vínculos, Events y metadata de PipelineRuns.

## Bugs/hallazgos y veredicto MVP

**Reproducidos:**

1. **Fusión incorrecta por Level 1:** dos nombres compartidos no identifican un suceso. Ignora diferencias explícitas de esquina, vehículo y hora; Rosario + Pellegrini alcanza para fusionar C. Bloqueante frente a la prioridad declarada de evitar fusiones erróneas.
2. **Fusión incorrecta por score alto controlado:** la rama alta carece de comprobación de contradicciones. Los hechos distintos de C se fusionan con s=0.94. No demuestra la frecuencia de ese score en Voyage; sí demuestra la ausencia de una defensa cuando ocurra.
3. **Interferencia del gate:** los accidentes comunes de A/B/C se descartan antes de dedup con la configuración editorial actual. A/B solo se evalúan como dedup aislado, no como cobertura editorial real.
4. **Información asimétrica para Terra:** faltan campos estructurados del Event existente; comprobado en payload capturado. El routing responde correctamente a los fakes, pero no prueba que el modelo pueda juzgar conflictos que no recibe.
5. **B no actualiza resumen/embedding del Event:** mantiene el mismo Event y agrega fuente; la novedad queda en SourceItem B. Comprobado, sin intervenir etapas posteriores.

**Riesgos de inspección, sin reproducción adicional en esta matriz:** `EXISTING_EVENT` acepta cualquier UUID que exista en DB, aunque no esté en el top enviado, y no usa confidence; consulta limitada a 40 y fallback solo cuando el filtro no devuelve nada pueden ocultar un match verdadero; la ventana es por detección; no se verifica modelo del embedding almacenado antes de compararlo. No se evaluaron concurrencia, rendimiento ni embeddings/Terra reales.

**DEDUP NO APTO PARA MVP.** A/B y el enrutamiento de D funcionan bajo condiciones controladas, pero C falla por dos caminos. En particular, Level 1 produce una fusión equivocada independiente de la calidad de embeddings. Se requiere autorización posterior para corregir; esta tarea deja únicamente tests y documentación de evaluación.
