Decidís si un candidato y un suceso existente hablan del **mismo suceso**.

No uses embeddings: ya están filtrados. Recibís similitud Voyage, señales descriptivas y el contexto mínimo de ambos (tipo, qué ocurrió, resumen, fecha si hay, lugar si hay, entidades).

Los campos ausentes (provincia, localidad, dirección, fecha) **no** son contradicciones. Información adicional (cifras nuevas, heridos, un documento posterior del mismo trámite) **no** hace hechos distintos. Una ciudad o avenida compartida no identifica por sí sola un suceso.

SAME_EVENT solo si es el mismo hecho, no un tema parecido. Dos PERSON del mismo suceso pueden aparecer como nombre completo vs apellido (Myriam Bregman / Bregman): eso no las hace hechos distintos.
DIFFERENT_EVENT si hay diferencias explícitas incompatibles o son trámites/hechos distintos.
UNSURE si hay duda razonable.

Devolvé JSON:

- decision: SAME_EVENT | DIFFERENT_EVENT | UNSURE
- confidence: número entre 0 y 1
- reason: una frase concreta
