A partir del texto de una publicación, extraé un suceso factual. No inventes datos que no estén en el texto. Si un campo no está, usá null.

Devolvé JSON con este esquema:

- event_type: tipo breve en minúsculas (incendio, accidente, protesta, homicidio, anuncio_oficial, otro)
- what_happened: qué ocurrió, en una o dos frases, sin adjetivos editoriales
- occurred_at: fecha/hora ISO 8601 si se infiere; si no, null
- country_code: ISO 3166-1 alpha-2; por defecto AR si el texto es de Argentina. No asumas un país si el texto apunta a otro.
- province, locality, neighborhood, address_text: solo si aparecen con evidencia en el texto
- latitude, longitude: solo si el texto las da; si no, null
- location_confidence: número 0–1 según cuán clara es la ubicación en el texto (1 = localidad explícita, 0 = no se puede saber)
- entities: lista de {name, entity_type, role}
  - entity_type: PERSON | ORGANIZATION | COMPANY | GOVERNMENT | PLACE | OTHER
  - role: protagonista | lugar | organismo | testigo | mencionado
- short_summary: resumen corto, informativo, sin juicio
- editorial_scope: uno de
  - GENERAL_NEWS: noticia de interés público que no es deporte de fandom
  - SPORTS_ONLY: resultado, fixture, transferencia, crónica de partido o contenido de hinchada sin impacto público
  - SPORTS_PUBLIC_IMPACT: ligado al deporte pero con impacto público (violencia, heridos, disturbios, infraestructura, delito, salud)
  - IRRELEVANT: publicidad, opinión sin hecho, farándula, receta, ranking, u otro texto sin suceso factual noticiable
- editorial_reason: una frase que justifique el scope; no inventes hechos

Ubicación:
- No inventes localidad. Si solo hay país o provincia, dejá locality en null.
- Si el texto dice una ciudad que no es Rosario, cargala igual (el filtro posterior decide).
- locality puede ser "Rosario" o "Rosario, Santa Fe" si ambas aparecen.

Deportes:
- Un gol, un partido, Colapinto en F1, la tabla, un refuerzo de Newell's o Central → SPORTS_ONLY.
- Disturbios con heridos en un estadio, un club usado como escenario de un crimen, o un hecho deportivo que altera el espacio público → SPORTS_PUBLIC_IMPACT.

El color y el tono no expresan ideología. No clasifiques actores como buenos o malos.
