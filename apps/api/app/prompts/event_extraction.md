A partir del texto de una publicación, extraé un suceso factual. No inventes datos que no estén en el texto. Si un campo no está, usá null JSON (sin comillas), nunca los strings "null", "none", "undefined", "nil", "n/a" o "unknown" en campos opcionales.

Primero identificá en what_happened qué acontecimiento está informando realmente la publicación; después clasificá ESE acontecimiento en event_type.
event_type clasifica exclusivamente el SUCESO PRINCIPAL que la publicación está informando. No debe derivarse de antecedentes, contexto histórico, delitos de fondo, causas anteriores, biografías ni hechos secundarios.
No exijas que el suceso haya ocurrido ahora: puede ser antiguo si es el asunto principal informado.

Devolvé JSON con este esquema:

- what_happened: el suceso principal informado, en una o dos frases, sin adjetivos editoriales. Describí el asunto concreto con los datos del texto; no te limites a decir "la nota describe..." o "la publicación informa...". Conservá la atribución cuando corresponda. Nunca uses los literales null, none o undefined. Si no hay un hecho claro, copiá el dato factual del título o del texto; no inventes un acontecimiento para poder asignar una categoría.
- event_type: tipo breve en minúsculas del acontecimiento identificado en what_happened. Ejemplos ilustrativos, no una lista cerrada: incendio, accidente, protesta, homicidio, anuncio_oficial, decreto, eleccion, festival, otro. Podés usar un tipo libre más preciso (judicial, propiedad, informe_propiedad, etc.) si está respaldado por el suceso principal. No copies un ejemplo que no describa ese acontecimiento. Si no podés determinar un tipo con seguridad, usá otro. Un festival, feria o programación cultural no es una protesta.
- occurred_at: instante ISO 8601 solo si la fuente da una hora explícita del SUCESO PRINCIPAL y permite identificar su fecha. La marca Publicado es metadata de la publicación, no la hora del suceso: no la copies a occurred_at. Si solo hay fecha, "este lunes", "por la tarde" o una hora aproximada, usá null; conservá la fecha o referencia temporal en what_happened/short_summary si aporta información. No completes una fecha con 00:00:00 ni con la hora de publicación. Una hora de un antecedente u otro hecho tampoco fecha el suceso principal. Conservá la hora cuando sí sea explícita, incluida medianoche si el texto la expresa.
- country_code: ISO 3166-1 alpha-2; por defecto AR si el texto es de Argentina. No asumas un país si el texto apunta a otro.
- province: jurisdicción administrativa de primer nivel del lugar del suceso (provincia o ciudad autónoma), no el alcance territorial de una medida ni el lugar de un antecedente.
- locality: ciudad o localidad donde ocurre el suceso, separada de la provincia; no coloques aquí un barrio.
- neighborhood: barrio dentro de esa localidad, solo si está identificado; no reemplaza a province o locality.
- address_text: dirección o intersección del suceso, solo con evidencia explícita.
- Geografía: no inventes niveles ausentes. CABA / Ciudad Autónoma de Buenos Aires es una jurisdicción distinta de la Provincia de Buenos Aires. Si el suceso ocurre en CABA, usá country_code="AR", province="Ciudad Autónoma de Buenos Aires" y locality="Ciudad Autónoma de Buenos Aires"; conservá el barrio aparte si aparece. Nunca combines province="Buenos Aires" con locality="Ciudad Autónoma de Buenos Aires". Si el texto dice Provincia de Buenos Aires (por ejemplo, La Plata), usá province="Buenos Aires" y la localidad respaldada por el texto; no lo conviertas a CABA. "Buenos Aires" sin contexto suficiente no permite decidir entre ciudad y provincia: dejá en null el nivel no determinado.
- latitude, longitude: solo si el texto las da; si no, null
- location_confidence: número 0–1 según cuán clara es la ubicación en el texto (1 = localidad explícita, 0 = no se puede saber)
- entities: lista de {name, entity_type, role}
  - entity_type: PERSON | ORGANIZATION | COMPANY | GOVERNMENT | PLACE | OTHER
  - GOVERNMENT es un organismo del Estado (ministerio, municipio, Congreso, Boletín Oficial, ente regulador). Un medio de prensa, diario, portal, radio o canal NO es GOVERNMENT; usá ORGANIZATION o COMPANY.
  - role: protagonista | lugar | organismo | testigo | mencionado
  - role organismo: solo actores institucionales (ministerio, ente, poder del Estado). Una ley, un régimen penal, un decreto o una norma NO van con role organismo.
  - Si una PERSON es solo el apellido u otro sufijo tokenizado de otra PERSON del mismo texto (p. ej. Bregman y Myriam Bregman), listá una sola, la forma más completa.
- short_summary: resumen corto, informativo, sin juicio. No inviertas cualificadores de edad, alcance o vigencia. Si el texto dice que algo no se aplica a menores, o que rige desde una fecha, el resumen no debe afirmar lo contrario. Este resumen alimenta la investigación y la redacción.
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

Ejemplos de precisión temporal y geografía:
- "El ministro presentó la medida el 14 de septiembre de 2026", con Publicado=2026-09-14T18:30:00Z → occurred_at=null: la fuente no da la hora del anuncio.
- "Este lunes se anunció la medida en la Ciudad Autónoma de Buenos Aires" → occurred_at=null, province="Ciudad Autónoma de Buenos Aires", locality="Ciudad Autónoma de Buenos Aires".
- "El acto ocurrió el 14 de septiembre de 2026 a las 14:00, hora argentina, en La Plata, Provincia de Buenos Aires" → occurred_at="2026-09-14T14:00:00-03:00", province="Buenos Aires", locality="La Plata".

Ejemplos de suceso principal y event_type:
- A. Un tiroteo dejó una persona asesinada y ese es el suceso principal → homicidio.
- A2. Una publicación informa que una muerte de hace dos años fue determinada como homicidio → homicidio puede ser correcto: la antigüedad no lo excluye.
- B. Un juez resolvió una apelación en una causa por homicidio → judicial (o el tipo del acto judicial) u otro si no es seguro; no homicidio. what_happened describe la resolución. Lo mismo vale para un fallo o procesamiento: el delito de fondo no es el acto informado.
- C. Un informe sobre propiedades de actores políticos menciona una condena por homicidio o un arresto domiciliario como contexto → propiedad, informe_propiedad u otro si no es seguro; no homicidio.
- D. Hay un dato factual, pero no un tipo claro → otro; conservá ese dato en what_happened sin inventar un hecho para encajar una categoría.
- E. San José 1111: un informe vincula a dirigentes con departamentos en el edificio donde una persona cumple prisión domiciliaria y menciona causas o condenas por homicidio como antecedentes → informe_propiedad, propiedad u otro si no es seguro; no homicidio. what_happened debe expresar el vínculo informado con los departamentos y su atribución, sin inventar una compraventa, un arresto ni una resolución judicial.
Usá homicidio solo cuando describa el suceso principal identificado en what_happened, no por la mera mención de un homicidio, una víctima, una condena o una causa en el contexto.

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
- No uses protesta, incendio, accidente ni homicidio si no describen el suceso principal informado. "Sede de torneos" o "son locales" no es una protesta.

El color y el tono no expresan ideología. No clasifiques actores como buenos o malos.
