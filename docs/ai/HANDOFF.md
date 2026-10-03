# Handoff

**Fecha:** 2026-10-03

**Tarea:** Cerrar la decisión de modelos en `feat/costos-deepseek-cache`, worktree `E:\sin-linea-wt-costos`. Sin merge, push ni despliegue. `main` sigue en `f4f1b07`.

## Política de verificación

Se reaplicó cada juicio guardado desde `input_evidence`, con admisión, `assess_origins` y la política, y se revirtió la sesión. La evidencia y los metadatos quedaron iguales.

| Claim | Orígenes admitidos | Modelo | Persistible |
| --- | --- | --- | --- |
| `84d4352c`, sin vínculo de Chazarreta con los disparos | 1, `derechadiario.com.ar` | gpt-4o `SINGLE_SOURCE`; Pro `SUPPORTED` | `SINGLE_SOURCE` |
| `fb6ac81f`, un disparo y estado grave | 1, `nubenoticias.com.ar` | gpt-4o `SINGLE_SOURCE`; Pro `SUPPORTED` | `SINGLE_SOURCE` |
| `55ca7750`, condena de 4 años y 6 meses | 3 medios, ninguna primaria judicial | Pro `SUPPORTED`; gpt-4o `SINGLE_SOURCE` | `SINGLE_SOURCE` |

En los dos de La Tablada el plan pide corroboración independiente y hay un solo origen informativo. Pro los da por corroborados; la política no. En la condena el plan exige registro judicial. Tres medios no reemplazan esa primaria, así que el estado es `SINGLE_SOURCE` con `MISSING_DOCUMENTARY_PRIMARY`. El replay de gpt-4o tenía excerpts cortados a 240 caracteres y por eso contó dos orígenes y otra razón; el status igual fue `SINGLE_SOURCE`. No se repitió esa llamada.

La compuerta `needs_sol_after_assessment` coincidió en escalar o no en todos los claims medidos. Flash no se salteó el juicio de la condena ni el de los dos de La Tablada, y no agregó una escalada que Nano no hiciera. En la consigna de la marcha ambos no escalan: Flash porque la evaluación ya tiene primaria auténtica; Nano porque no le quedó soporte admitido. En la inhabilitación, el plan de Nano pediría corroboración y, con un origen, escalaría; el de Flash no. El estado ya guardado es `SINGLE_SOURCE`.

Ruta real de la condena, con el perfil candidato: evaluación Flash USD 0.002472396, juicio Pro USD 0.004507140 y tres búsquedas USD 0.021. Total USD 0.027979536. El contravalor Nano + gpt-4o, sin repetir la búsqueda, sale USD 0.035065100. La marcha no llamó a Pro: evaluación USD 0.001653258 más dos búsquedas USD 0.014.

## Extracción, research y planificación

Mismos textos persistidos. No hubo otro poll. No se exigió texto idéntico.

La extracción de Flash y de Nano deja pasar el gate, con la misma localidad y provincia, y describe el mismo incidente en los cuatro sucesos. El `event_type` libre no coincide en tres (`condena`/`judicial`, `marcha`/`protesta`, `protesta`/`denuncia`). La Tablada coincide en `homicidio`. Ninguno pidió el fallback de lugar.

Las consultas del poll salieron del código. La relevancia se rehizo solo sobre documentos ya guardados, con el inicio del texto y no el snippet original. En la marcha, Nano marcaría contexto —y no adjuntaría— el recorrido, los cortes y un resumen de finde que Flash adjuntó. En Formosa, Flash dejaría fuera notas del mismo caso y rechazaría una nota distinta sobre Adorni que sí estaba adjuntada. No se volvió a verificar con el otro conjunto.

Después de `refine_plan`, 2 de 13 planes coinciden en las decisiones que cambian la búsqueda o la compuerta. Flash pasa los dos claims de La Tablada de `JUDICIAL_RECORD` a `INDEPENDENT_CORROBORATION`. Esa búsqueda no se repitió.

## Auditoría

La atribución agregada en la bajada de la marcha sigue la regla vigente. La consigna `50961d28` es `SUPPORTED` y es un dicho: `attribution_required` queda en true. `structural_findings` de la V1 marca `surface_attribution` alto. Ese hallazgo es de código. La primera auditoría de Flash devolvió 10 tokens de completion (USD 0.000281628). La reescritura la hizo Luna, USD 0.003340670, y la segunda auditoría de Flash costó USD 0.000451728. La V2 ya no tiene ese hallazgo alto. gpt-4o también pasaba el texto; el estructural igual obliga la reparación.

## Gasto en `sin_linea_costos`

Todo calculado. Cero costos desconocidos.

| Tramo | USD | Llamadas |
| --- | --- | --- |
| Ensayo corto | 0.043922640 | 34 |
| Descarte deportivo | 0.000883050 | 1 |
| Poll, dos notas | 0.089172062 | 35 |
| Replay de prompts reales | 0.126329412 | 51 |
| Extracción, plan y relevancia | 0.016948358 | 21 |
| Total | 0.277255522 | 142 |

Quedan USD 2.722744478 de los 3.

## Configuración propuesta

No activar el perfil entero. `ultra_light_processing` mezcla extracción, relevancia, plan y evaluación.

```
COST_PROFILE=candidate
COST_PROFILE_ROLES=verification,auditing
SEARCH_CACHE_ENABLED=true
VERIFICATION_REUSE_ENABLED=true
```

Para volver atrás: `COST_PROFILE=current`, `COST_PROFILE_ROLES=` vacío, `SEARCH_CACHE_ENABLED=false`, `VERIFICATION_REUSE_ENABLED=false`.

Frescura: una búsqueda idéntica puede ocultar una página nueva hasta 30 minutos. Una verificación reutilizada no busca de nuevo hasta 2 horas si el paquete no cambió. Una fuente nueva, una corrección, otro excerpt, otra procedencia, otro hash, otro modelo o un resultado fallido no esperan el TTL.

## Sigue sin comprobar

Dedup, resolución de claims y prompt de imagen no tuvieron un caso. No se rehizo la búsqueda con el otro plan ni con los documentos que el otro modelo habría adjuntado. El excerpt completo de gpt-4o en la condena no se volvió a pedir. Estas banderas no están puestas en el entorno aislado ni en `main`.
