Decidí cómo se relaciona cada resultado de búsqueda con el suceso del Event (mismo hecho, lugar y momento aproximado). No evalúes calidad periodística ni ideología.

Usá solo título, URL y snippet. No inventes contenido de la página.

Para cada URL devolvé classification:
- SAME_EVENT: claramente el mismo suceso (mismo hecho, lugar y ventana temporal)
- RELATED_CONTEXT: el mismo tema o lugar pero otro hecho, antecedentes o contexto
- DIFFERENT_EVENT: otro suceso concreto (otra ciudad, otra fecha, otra víctima)
- IRRELEVANT: no habla de un suceso comparable

confidence: 0–1. Si dudás entre SAME_EVENT y otra cosa, no uses SAME_EVENT.

Devolvé JSON: { "hits": [ { "url": "...", "classification": "SAME_EVENT", "confidence": 0.8 } ] }
Incluí todas las URLs recibidas.
