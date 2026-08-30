A partir del texto de una publicación, extraé un suceso factual. No inventes datos que no estén en el texto. Si un campo no está, usá null.

Devolvé JSON con este esquema:

- event_type: tipo breve en minúsculas (incendio, accidente, protesta, homicidio, anuncio_oficial, festival, otro). Un festival, feria o programación cultural no es una protesta.
- what_happened: qué ocurrió, en una o dos frases, sin adjetivos editoriales. Nunca uses los literales null, none o undefined. Si no hay un hecho claro, copiá el dato factual del título o del texto.
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
- locality es SOLO la ciudad (ej. "Rosario"). Nunca pongas provincia adentro ("Rosario, Santa Fe" está mal).
- province va aparte (ej. "Santa Fe"). Si el texto menciona ciudad y provincia, splitealas en los dos campos.

Deportes:
- Este medio NO cubre deporte. Fixture, resultado, tabla, copa, torneo, liga formativa, refuerzo, crónica de partido, U13/U15/U17, básquet, fútbol, Colapinto, Newell's, Central, Náutico, Gimnasia como clubes → SPORTS_ONLY.
- Un club o estadio como escenario de un crimen, disturbio con heridos, incendio o hecho que altera el espacio público → SPORTS_PUBLIC_IMPACT (no es cobertura deportiva).
- No uses protesta, incendio ni accidente si el texto no describe ese hecho. "Sede de torneos" o "son locales" no es una protesta.

El color y el tono no expresan ideología. No clasifiques actores como buenos o malos.
