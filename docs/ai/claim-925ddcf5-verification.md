# Claim 925ddcf5 — diagnóstico y corrección de Verification

Verificado el 2026-09-12. Alcance: Claims, Verification y resolución. Auditor sin cambios. No se reescribió ni publicó el artículo. La inspección inicial fue de solo lectura; la reevaluación posterior usó los proveedores configurados por pedido del usuario.

Suceso: `42761183-eca5-4f6d-80ca-874efa7e919c`. Artículo: `milei-anticipo-mas-reformas-si-logra-la-reeleccion-en-2027`. Claim: `925ddcf5-e07a-47c6-a30e-e39477ea06e2`.

## Causa confirmada

La atribución se conservaba en la oración pero se estructuró como un hecho económico: `claim_type=hecho`, sujeto `Gobierno de Javier Milei`, `normalized_value=2`, `unit=porcentaje`, `occurred_at=null`. Se omitió el ancla temporal del original. Verification planificó estadísticas oficiales sin período y el modelo emitió una conclusión universal que no se desprendía de los tres meses citados. `_apply_result` aceptaba ese DISPROVEN; `apply_primary_requirement` solo limitaba SUPPORTED y devolvía cualquier otro estado sin validar la contradicción.

No fue una comparación aritmética determinista. `try_resolve_numeric_comparison` busca marcadores de desigualdad que este claim no contiene. La evaluación barata guardó únicamente QUALIFIES para la nota periodística. Las tres relaciones CONTRADICTS aparecieron al aplicar el resultado final; no se guardó el JSON completo de ese resultado antiguo ni motivos individuales por documento. La atribución al modelo se confirma por ese recorrido de código y por los registros persistidos, no por una transcripción completa de su respuesta.

## Extracción y planificación históricas

Fragmento literal guardado de La Derecha Diario:

> The Economist reconoció que el Gobierno logró bajar la inflación desde niveles cercanos al 13% mensual antes de su llegada al poder hasta alrededor del 2%, además de alcanzar superávits fiscales y reducir significativamente la pobreza.

Claim histórico completo:

> The Economist reconoció que el Gobierno logró bajar la inflación desde niveles cercanos al 13% mensual hasta alrededor del 2%.

Plan guardado: `OFFICIAL_STATISTICS`, `STATISTICS`, `TIMELESS`, `year_hint=null`, jurisdicción AR, primaria y corroboración independiente requeridas. Términos: `Inflación`, `Milei`, `dos cifras`, `13%`, `2%`. El constructor tomaba solo los primeros cuatro y produjo:

```text
Inflación Milei "dos cifras" 13% site:indec.gob.ar
Inflación Milei "dos cifras" 13%
```

Son las consultas guardadas por el servicio, no un log de cada petición HTTP. No había períodos inicial/final ni tolerancia documentada. El indicador mensual y los extremos aproximados sobrevivían en el texto, pero la única magnitud estructurada era 2. No se dispone del JSON bruto de extracción o del plan previo a su refinamiento.

## Evidencias históricas, sin truncar sus excerpts

Las tres tenían `confidence=0.9`, `body_source=search_snippet`, `fetch_ok=false`: se almacenaron snippets de URLs del INDEC, no el cuerpo descargado del PDF.

Agosto de 2026:

> El nivel general del Índice de precios al consumidor registró un alza mensual de 1,7% en agosto de 2026

Junio de 2026:

> El nivel general del Índice de precios al consumidor registró un alza mensual de 1,9% en junio de 2026

Abril de 2026:

> El Nivel general del Índice de precios al consumidor registró un alza mensual de 2,6% en abril de 2026

Motivo global del modelo, guardado literalmente:

> Los datos del INDEC muestran que la inflación mensual nunca estuvo cerca del 13% ni bajó a alrededor del 2% durante el periodo mencionado. La afirmación de The Economist no se sostiene con las estadísticas oficiales.

No hay razonamientos individuales guardados que expliquen por qué cada mes sería incompatible. Los excerpts no establecen qué declaró The Economist, no cubren el extremo inicial y no permiten inferir “nunca”. Las cifras 1,7% y 1,9% tampoco refutan por desigualdad exacta una aproximación a 2%. Esto invalida la justificación del desmentido; no demuestra la verdad de toda la trayectoria.

## Corrección implementada

- `claim_meaning.preserve_extracted_meaning` conserva el dicho como declaración y su emisor; recupera el tramo temporal literal de la evidencia citada cuando coinciden ambos extremos. Las trayectorias no se reducen a un escalar final. La cadena de atribución conserva fuente y excerpt; Verification la registra como `attributed_report`.
- El plan usa `PRIMARY_STATEMENT` para el dicho y `UNKNOWN_PERIOD` para una trayectoria sin extremos fechados. La búsqueda conserva el texto material completo; no introduce “dos cifras” ni descarta 2%. No se inventa una fecha de asunción.
- `EvidenceComparison` incorpora fragmentos y coordenadas de cada observación. `valid_contradiction` comprueba que consten en el texto y correspondan en indicador, unidad, ámbito y período; exige documento extraído y que la comparación aparezca en el excerpt citado. Los snippets de búsqueda no bastan para un desmentido.
- El redondeo a la precisión expresada sirve únicamente para descartar una contradicción. Fuera de ese redondeo sigue haciendo falta una explicación contextual de incompatibilidad; no se fijó una tolerancia universal. Compatibilidad parcial queda QUALIFIES; falta de correspondencia, MENTIONS.
- `_apply_result` exige una contradicción admitida y efectivamente adjuntada. Un DISPROVEN sin ella queda SINGLE_SOURCE si hay respaldo, o UNCERTAIN si falta. Los datos económicos no refutan por sí mismos una atribución. Claims remite sospechas de falsedad a Verification; un claim hermano confirmado tampoco desmiente automáticamente al otro.
- La reevaluación explícita por ID atraviesa los servicios existentes y conserva identidad e historial. Guarda extracción, estado/evidencias anteriores, packet, salida del verificador y controles aplicados. La evaluación nueva puede reemplazar una relación errónea anterior; CONTRADICTS dejó de ser irreversible por prioridad numérica.

## Reevaluación real

Comando de entrada: `python scripts/reverify_claim.py --claim-id 925ddcf5-e07a-47c6-a30e-e39477ea06e2`, ejecutado en el entorno Compose con el código del workspace montado. Usa `ClaimService.resolve` y `VerificationService.verify`; no asigna manualmente estados. Proveedores configurados: extracción OpenAI/gpt-4o-mini, resolución DeepSeek/deepseek-chat, planificación/evaluación barata OpenAI/gpt-5-nano, verificación OpenAI/gpt-4o y búsqueda Exa.

| Etapa | Run histórico conservado | Nuevo run SUCCESS |
|---|---|---|
| Claims | f5c2e2e2-cdb2-443f-973b-4988bb4e4e34 | 232fd5b8-d231-4a60-a1a1-99cffc37e9f3 |
| Verification | 669633e1-362d-4b8a-846d-e9791669a7fa | b254e936-1d27-4310-8beb-c0eca00798fd |

Resultado: **DISPROVEN → SINGLE_SOURCE**, conservando el ID. Nuevo texto:

> The Economist reconoció que el Gobierno logró bajar la inflación desde niveles cercanos al 13% mensual antes de su llegada al poder hasta alrededor del 2%.

Ahora es `declaracion`, sujeto `The Economist`, `normalized_value=null`; la trayectoria completa queda en `object_text`. Ese mismo texto completo fue la consulta generada. Plan: `PRIMARY_STATEMENT`, `PUBLIC_STATEMENT`, `UNKNOWN_PERIOD`, sin año inventado.

Evidencias actuales:

- La Derecha Diario: SUPPORTS de la atribución reportada; excerpt literal conservado hasta “alrededor del 2%”. `statement_evidence_class=attributed_report`, `primary_access=not_found`, un documento de respaldo. No se acreditó publicación original de The Economist.
- INDEC, 1,7% agosto / 1,9% junio / 2,6% abril: MENTIONS, con los excerpts históricos citados arriba.
- Un resultado adicional de mnewseconomist.com.ar menciona “la caída de la inflación mensual del 13% al 3%”: MENTIONS. El verificador no lo usa como confirmación de la atribución.

La salida nueva del modelo fue SINGLE_SOURCE por falta de evidencia primaria directa de The Economist. La trayectoria económica no quedó confirmada ni se creó una proposición estadística adicional en esta reevaluación limitada al dicho. Los otros claims quedaron fuera del recheck; este run no pretende completar la verificación del suceso entero.

## Pruebas

149 tests pasaron en `sin_linea_claim_comparison_test`, separada de la base editorial, con dobles de modelos y búsqueda. Incluyen 19 regresiones nuevas: atribución y ancla temporal, ambos valores en búsquedas, 1,7/1,9 compatibles con redondeo pero insuficientes para toda la trayectoria, período/ámbito/indicador diferentes, falta de coordenadas o documento original, aproximación no resuelta, 25% contra ~2% para el mismo IPC/ámbito/mes, prohibición de trasladar esa refutación al dicho, rechazo de DISPROVEN sin comparación, correspondencia con el excerpt mostrado, conservación de ID/historial y recheck explícito de un claim desmentido.

Suites: `test_proposition_comparison`, `test_claims`, `test_verification`, `test_verification_plan`, `test_prompt_payloads`, `test_editorial_evidence`, `test_editorial_label_policy`, `test_claim_card_presentation`. Dos warnings de deprecación de dependencias. La reevaluación real descrita arriba es distinta de esas pruebas con dobles.
