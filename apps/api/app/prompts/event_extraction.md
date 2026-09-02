A partir del texto de una publicación, extraé un suceso factual. No inventes datos que no estén en el texto. Si un campo no está, usá null.

Devolvé JSON con este esquema:

- event_type: tipo breve en minúsculas (incendio, accidente, protesta, homicidio, anuncio_oficial, decreto, eleccion, festival, otro). Un festival, feria o programación cultural no es una protesta.
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
  - GENERAL_NEWS: suceso factual que no es deporte de fandom ni publicidad
  - SPORTS_ONLY: resultado, fixture, transferencia, crónica de partido o contenido de hinchada sin impacto público/político
  - SPORTS_PUBLIC_IMPACT: ligado al deporte pero con dimensión institucional o política (no alcanza con heridos en un estadio)
  - IRRELEVANT: publicidad, opinión sin hecho, farándula, receta, ranking, u otro texto sin suceso factual noticiable
- editorial_reason: una frase que justifique el scope; no inventes hechos
- editorial_topic: uno de NATIONAL_POLITICS | PROVINCIAL_POLITICS | GOVERNMENT | LEGISLATION | ELECTIONS | PUBLIC_ECONOMY | PUBLIC_SECURITY | PUBLIC_EDUCATION | PUBLIC_HEALTH | JUSTICE | CORRUPTION | INTERNATIONAL_AR | OTHER_PUBLIC_AFFAIRS | CRIME | ACCIDENT | SPORTS | ENTERTAINMENT | OTHER
- is_public_affairs: true solo si el suceso pertenece materialmente a política, gobierno, administración pública o interés público institucional de Argentina (o con impacto argentino). Un choque, un robo común, un incendio cotidiano, fútbol, celebridades o clima NO son public affairs.
- political_relevance: NONE | LOW | MEDIUM | HIGH según la dimensión política/institucional material. MEDIUM o HIGH solo si hay decisión pública, funcionario, ley, elección, presupuesto, denuncia institucional o equivalente.
- public_interest_relevance: NONE | LOW | MEDIUM | HIGH como señal auxiliar. Un accidente puede ser de interés y aun así NO ser public affairs.
- has_contestable_public_claims: true si el texto contiene afirmaciones públicas verificables (cifras, acusaciones, decisiones). No uses esto como único criterio de inclusión.
- argentina_relevance: true solo si hay relación material con Argentina (hecho en el país, decisión argentina, impacto argentino, actor institucional argentino). Una noticia política extranjera sin vínculo argentino es false. No marques true por omisión.
- gate_reason: una frase que explique por qué entra o no al alcance de política/asuntos públicos argentinos.

Ubicación:
- No inventes localidad. Si solo hay país o provincia, dejá locality en null. Una noticia nacional (decreto, Congreso, Presidencia) puede no tener ciudad.
- Si el texto dice una ciudad argentina (Buenos Aires, Córdoba, Rosario, Mendoza, Tucumán, Santa Fe, etc.), cargala. El filtro posterior ya no exige Rosario.
- locality es SOLO la ciudad (ej. "Rosario"). Nunca pongas provincia adentro ("Rosario, Santa Fe" está mal).
- province va aparte (ej. "Santa Fe"). Si el texto menciona ciudad y provincia, splitealas en los dos campos.

Alcance editorial (política y asuntos públicos de Argentina):
- Entra: política nacional o provincial; gobierno; administración pública; Presidencia; gobernaciones; Congreso; legislación; elecciones; partidos; funcionarios; política económica; presupuesto; impuestos; jubilaciones/pensiones por decisión pública; empleo y regulación laboral como política pública; seguridad, educación o salud como política pública; justicia con relevancia institucional/política; causas judiciales contra funcionarios o actores políticos; corrupción; transparencia; organismos del Estado; relaciones internacionales con impacto argentino; declaraciones políticas materialmente relevantes; datos públicos usados en el debate político.
- No entra: choque de autos; incendio cotidiano; robo o policial común sin dimensión institucional; deportes; entretenimiento; celebridades; clima común; sucesos locales rutinarios.
- Un hecho policial entra SOLO si hay dimensión institucional/política material. “Dos personas robaron un comercio” → is_public_affairs false. “Investigan al ministro de Seguridad por una contratación irregular” → true.

Deportes:
- Este medio NO cubre deporte. Fixture, resultado, tabla, copa, torneo, liga formativa, refuerzo, crónica de partido, U13/U15/U17, básquet, fútbol, Colapinto, Newell's, Central, Náutico, Gimnasia como clubes → SPORTS_ONLY, editorial_topic SPORTS, is_public_affairs false.
- Un club o estadio como escenario de un crimen o disturbio NO alcanza para public affairs salvo dimensión institucional (p. ej. investigación a un funcionario).
- No uses protesta, incendio ni accidente si el texto no describe ese hecho. "Sede de torneos" o "son locales" no es una protesta.

El color y el tono no expresan ideología. No clasifiques actores como buenos o malos.
