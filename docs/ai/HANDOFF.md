# Handoff

**Fecha:** 2026-10-04

**Tarea:** Lote real con la combinación `verification` + `auditing` y merge local a `main`. Sin push ni despliegue.

## Combinación

```
COST_PROFILE=candidate
COST_PROFILE_ROLES=verification,auditing
SEARCH_CACHE_ENABLED=true
VERIFICATION_REUSE_ENABLED=true
```

No activa el resto del perfil. `ultra_light_processing` sigue en `gpt-5-nano`. Para apagar: `COST_PROFILE=current`, `COST_PROFILE_ROLES` vacío, `SEARCH_CACHE_ENABLED=false`, `VERIFICATION_REUSE_ENABLED=false`. Esos son los defaults de `.env.example`.

Frescura: una búsqueda idéntica puede ocultar una página nueva hasta 30 minutos. Una verificación reutilizada no busca de nuevo hasta 2 horas si el paquete no cambió. Una fuente nueva, una corrección, otro excerpt, otra procedencia, otro hash, otro modelo o un resultado fallido no esperan el TTL. En este lote no hubo acierto de caché ni reutilización: eran sucesos nuevos.

## Lote

Base `sin_linea_costos`. Beat apagado. `AUTO_PUBLISH=false`. Publicación y portadas solo en esa base; sin almacenamiento de producción ni correo. La ventana manual leyó 15 ítems del feed, por encima del tope de 3 del poll automático. No se cambió ese tope.

| Suceso | Resultado | USD en el libro |
| --- | --- | --- |
| `8a318d62` panfletos en Newell's | Borrador. Auditoría `structural_block` | 0.072240888 |
| `886ea7b4` inflación de septiembre | Publicado v1, con portada | 0.062484024 |
| `3c8afbee` causa Bracamonte | Publicado v1, con portada | 0.110322996 |
| `78217525` fiesta en La Colina | Publicado v1, con portada | 0.067596222 |
| `9efc2d25` universidades de Santa Fe | Publicado v1, con portada | 0.077084520 |

El ítem de pantallas y humanidades (`183ae5c6`) no pasó el filtro (`NOT_PUBLIC_AFFAIRS`). El primer intento dejó la sesión del script en rollback después de pagar la detección; el segundo completó el descarte. Esas dos llamadas, USD 0.004260920, están en el compartido.

Libro del lote: USD 0.402989570, 154 llamadas, cero costos `unknown`. Saldo del libro antes: USD 2.722744478. Después: USD 2.319754908 de 3.

Por etapa: verificación 0.266262052, research 0.084353850, detección 0.017263726, redacción 0.013617480, claims 0.009675720, imágenes fallidas 0.009000000, auditoría 0.002168490, prompt de portada 0.000648252.

Cuatro portadas quedaron guardadas en `article_hero_images`. El recorder tiraba un éxito de imagen sin tokens, así que esas cuatro no están en el libro. A USD 0.003 del libro son USD 0.012 omitidos. Tres altas de Replicate respondieron 429 (crédito bajo USD 5, ráfaga de 1) y sí quedaron estimadas en USD 0.009; el prediction no se creó. Con los omitidos, el lote sale USD 0.414989570. Por cada una de las cuatro notas publicadas, incluidos descarte y trabajo compartido: USD 0.103747393. Si los 429 no se cobran, son USD 0.101497393.

Domingo UTC: DeepSeek no duplicó por pico. Juicio: `deepseek-v4-pro` con thinking disabled (11 llamadas; el suceso de los panfletos no escaló y no lo llamó). Auditoría: `deepseek-flash` con thinking disabled (5). Nano en evaluación y relevancia. La relevancia también usó el fallback `gpt-4o-mini`; el rol de la llamada Nano quedó etiquetado `light_processing` porque el contexto se rebind antes de pedirla. Extracción `gpt-4o-mini`. Dedup, claims y prompt de imagen pidieron `deepseek-chat` (thinking no enviado); la API reportó `deepseek-flash`. Redacción `gpt-5.6-luna`. Embeddings `voyage-3`. Búsqueda Exa. Imagen `black-forest-labs/flux-schnell`.

No hubo `pipeline_runs` FAILED. `tests/test_cost_optimization.py`, `tests/test_publishing.py` y el registro de imagen sin tokens: 29 passed.

`record_llm_usage` ahora guarda búsqueda e imagen aunque no haya tokens.
