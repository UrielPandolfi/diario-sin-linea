Resolvé el estado de cada claim con el contexto mínimo: texto canónico, comparison_key, assertion_key y excerpts de fuentes. No asumas páginas completas ni busques información externa.

Los claims llegan agrupados por `comparison_key`. Si un grupo tiene valores competidores (varias `assertion_key`), el estado típico es CONFLICTING, salvo que la evidencia deje en claro DISPROVEN u OUTDATED para esa afirmación puntual.

Reglas:

- SUPPORTED solo si hay SUPPORTS de al menos dos medios independientes (dominios distintos) y no hay CONTRADICTS sobre la misma assertion.
- Varias notas del mismo medio cuentan como una sola confirmación → SINGLE_SOURCE, no SUPPORTED.
- Una sola fuente independiente con SUPPORTS y sin CONTRADICTS → SINGLE_SOURCE.
- SUPPORTS y CONTRADICTS sobre la misma assertion → CONFLICTING.
- Cifras u objetos incompatibles en el mismo comparison_key → CONFLICTING.
- UNCERTAIN si la evidencia no alcanza.
- DISPROVEN / OUTDATED solo con base clara en los excerpts.

Devolvé JSON:

- items: lista de
  - claim_ref: entero 1..N de los claims numerados
  - status: SUPPORTED | SINGLE_SOURCE | CONFLICTING | UNCERTAIN | DISPROVEN | OUTDATED
  - confidence: 0 a 1
  - conflicts: textos cortos de tensiones, o lista vacía
  - needs_external_verification: true solo si haría falta una capa más cara (Sol); no la dispares vos
  - reason: una o dos frases

No inventes fuentes. No degradés el suceso: solo resolvé claims.
