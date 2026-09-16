# Handoff

**Fecha:** 2026-09-14

**Tarea:** simplificación de dedup autorizada tras la revisión de generalidad.

## Resultado

**DEDUP GENERALIZADO — LISTO PARA PRUEBA CON VOYAGE REAL**. Esto acredita regresiones controladas; no calibra Voyage ni declara el dedup completo apto para producción.

**93 tests aprobados (18.02 s) + 2 integraciones (3.36 s)**. Un warning preexistente de Alembic por `path_separator` en cada ejecución, sin xfail ni skips.

- A, incluida variante sin entidades: 1 Event / 2 SourceItems / 2 EventSources; ejecución observada por `embedding_high:0.940`. Ya no se exige `level1_code` en el test.
- B: 1 Event / 2 SourceItems / 2 EventSources por embedding alto; la vinculación conserva resumen y embedding del Event existente.
- C bajo: 2 Events, `embedding_low:0.650`.
- C alto: 2 Events, `identity_conflict` por dirección diferente; sin veto temporal ni semántica de vehículos.
- C con Rosario/Pellegrini compartidos: 2 Events, `embedding_low:0.650`.
- D: score 0.80 consulta Terra; EXISTING_EVENT vincula y NEW_EVENT crea. Contrato simétrico intacto.
- Seis casos políticos con el gate real: mismo anuncio con redacciones diferentes (0.94 → embedding, 0.80 → Terra); anuncios en direcciones diferentes (0.94/0.80 → dos Events); mismo funcionario/organismo, dirección y timestamp con identidad ambigua (0.80 → Terra NEW); horas aproximadas diferentes (0.80 → Terra EXISTING, timestamps presentes en ambos lados del payload).

## Implementación vigente

`dedup_identity.py` ya no interpreta `what_happened` ni `short_summary`. Se eliminaron categorías/sinónimos de vehículos, regex de choque/colisión, pares, participantes adicionales, regex de horas y el umbral universal de dos horas. No hay nuevas reglas específicas de política/justicia.

`compare_identity` devuelve solamente `conflicts`: diferencias entre país/provincia/localidad presentes y direcciones explícitas de formatos comparables. Conserva normalización de tildes/caso/espacios, prefijos de calles, orden de intersecciones y direcciones numeradas. Información ausente o direcciones incomparables no son contradicción. La ausencia de conflictos no demuestra identidad.

No se utiliza el tiempo como veto: el esquema no informa precisión, fecha inferida/explícita ni si el hecho es puntual o prolongado. Tampoco hay identificador estructurado único del suceso. Por eso `_level1_match` mantiene su interfaz pero retorna None; el fast-path determinista vigente es la URL ya asociada. No se inventó otra combinación heurística de fecha/dirección/entidades para reemplazar la de choques.

Se conservan el filtro estructural previo a embedding_high/Terra, la consideración de candidatos alternativos y el rechazo de IDs que Terra no recibió o que fueron excluidos. Un score alto sin contradicciones detectadas todavía puede vincular directamente; la evaluación de identidad semántica con providers reales sigue pendiente.

Terra conserva el payload simétrico: what_happened (title_internal del existente), event_type, occurred_at (started_at), country_code, province, locality, neighborhood, address_text, entities con nombre/tipo/rol y short_summary; id/score adicionales para existentes. No hubo cambios al prompt en esta segunda implementación.

## Archivos modificados en esta segunda implementación

- `apps/api/app/services/dedup_identity.py`.
- `apps/api/app/services/detection_service.py`: retiro de la heurística positiva de Level 1 y su import sin uso.
- `apps/api/tests/test_dedup_identity.py`: 26 pruebas de estructura, tiempo desconocido y selección de candidatos; fixtures de selección ahora no relacionados con tránsito.
- `apps/api/tests/test_detection_dedup.py`: conserva las expectativas de A/B sin exigir Level 1; agrega seis casos políticos usando el mecanismo controlado existente.
- `docs/ai/DECISIONS.md`, `STATE.md` y este HANDOFF.

## Validación y evidencia

Base nueva `sin_linea_dedup_general_101dfd2665`, eliminada al finalizar. Desde `apps/api`, con DATABASE_URL apuntando exclusivamente a esa base:

```bash
python -m pytest tests/test_detection.py tests/test_detection_dedup.py tests/test_prompt_payloads.py tests/test_publication_outcome.py tests/test_dedup_identity.py -q --tb=short
python -m pytest tests/test_pipeline_politics.py tests/test_pipeline_publish.py -q --tb=short
```

Primera suite: 22 Detection + 17 dedup end-to-end controlados + 15 contratos de prompt + 13 publication outcome + 26 comparador/selección = 93. Segunda: 2 integraciones. No se editaron etapas posteriores para ejecutar estos tests.

Evidencia local fuera de Git: `.editorial-evals/dedup-generalized-20260914/`, con logs/XML de ambas suites, `traces.json`, snapshots previos de los cuatro archivos Python, `verification.json`, hashes de archivos protegidos y `environment.json`. Comparación AST confirma `_TEXTS`, `_candidates`, `_assert_outcome`, ambas funciones originales de C y la de D sin cambios. No se suavizaron los conteos de Events ni los vínculos.

## Alcance y pendientes

LOW/HIGH 0.72/0.88, ventana 72 h, Voyage provider, extracción/event_type, gate, localidades persistidas, tipos/roles de entidades y etapas posteriores intactos. Sin datos vivos ni llamadas reales. Los choques ordinarios siguen rechazados por el gate; solo sus pruebas de dedup aíslan explícitamente esa decisión. Los escenarios políticos pasan por el gate real.

La siguiente evaluación autorizable es extracción/Voyage reales con casos de mismo/diferente suceso. No se ejecutó ahora. Permanecen fuera: calibración, concurrencia, recuperación limitada a 40 candidatos, ventana por detección y actualizaciones del Event al incorporar fuentes.

Los informes y resultados anteriores en `.editorial-evals/dedup-fix-20260914/` y `dedup-evaluation-2026-09-14.md` son históricos; la heurística de choques/≥2 horas ya no está vigente.
