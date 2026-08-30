Decidí cómo se relaciona cada resultado de búsqueda con el suceso del Event (mismo hecho, lugar y momento aproximado). No evalúes calidad periodística ni ideología.

Usá solo título, URL y snippet. No inventes contenido de la página.

Para cada URL devolvé classification:
- SAME_EVENT: claramente el mismo suceso (mismo hecho concreto, no solo la misma ciudad y el mismo día)
- RELATED_CONTEXT: el mismo tema o lugar pero otro hecho, antecedentes o contexto
- DIFFERENT_EVENT: otro suceso concreto (otra ciudad, otra fecha, otra víctima, u otro acto oficial el mismo día)
- IRRELEVANT: no habla de un suceso comparable

Misma ciudad y misma fecha NO alcanzan para SAME_EVENT. Ejemplo: un Foro PyME en el Concejo y la inauguración de un muelle el mismo jueves en Rosario son DIFFERENT_EVENT.

confidence: 0–1. Si dudás entre SAME_EVENT y otra cosa, no uses SAME_EVENT.

Devolvé JSON: { "hits": [ { "url": "...", "classification": "SAME_EVENT", "confidence": 0.8 } ] }
Incluí todas las URLs recibidas.
