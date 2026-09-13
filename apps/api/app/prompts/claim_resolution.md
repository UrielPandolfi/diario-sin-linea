Resolvé el estado de cada claim con el contexto mínimo: texto canónico, comparison_key, assertion_key, occurred_at, published_at de cada fuente y excerpts. No asumas páginas completas ni busques información externa.

Los claims llegan agrupados por `comparison_key`. Varias `assertion_key` en el mismo grupo no son conflicto automático: pueden ser una actualización temporal (4 heridos a las 15:00, 6 confirmados a las 17:00).

Usá `occurred_at` (el momento al que se refiere la afirmación) y `published_at` (cuándo salió cada fuente):

- Mismo dato, mismo contexto temporal y valores incompatibles → CONFLICTING.
- Un dato anterior reemplazado por información posterior → el anterior OUTDATED; el nuevo se resuelve con las reglas normales (SUPPORTED / SINGLE_SOURCE / etc.).
- Si no se puede determinar si es contradicción o actualización → UNCERTAIN.
- DISPROVEN requiere una contradicción pertinente y comparable comprobada en Verification. En esta etapa, si sospechás contradicción, usá UNCERTAIN o CONFLICTING y needs_external_verification=true; no conviertas ausencia de prueba en falsedad.

Reglas por assertion:

- SUPPORTED si la evidencia es suficiente para el tipo de afirmación: reporting periodístico original de al menos dos procedencias demostradas e independientes, o fuente primaria/autoritativa cuando el claim la exige. Dos dominios o dos URLs no bastan por sí solos.
- Varias notas del mismo medio cuentan como una sola confirmación → SINGLE_SOURCE, no SUPPORTED.
- Sitios que reproducen esencialmente la misma versión (republicación, mismo texto, misma agencia, mismo comunicado, blogs personales) no son corroboración independiente.
- Una sola fuente independiente con SUPPORTS y sin CONTRADICTS → SINGLE_SOURCE.
- SUPPORTS y CONTRADICTS sobre la misma assertion → CONFLICTING.
- UNCERTAIN si la evidencia de esa assertion no alcanza.
- Leyes, cifras oficiales o materiales, expedientes y acusaciones de verdad no se marcan SUPPORTED por recuento de medios.

No trates como la misma assertion ni como CONFLICTING automático:

- la existencia de una denuncia, imputación o acusación versus la veracidad de lo denunciado;
- un dato oficial (IPC, decreto, fallo) versus una proyección, estimación privada o hipótesis de parte.

Devolvé JSON:

- items: lista de
  - claim_ref: entero 1..N de los claims numerados
  - status: SUPPORTED | SINGLE_SOURCE | CONFLICTING | UNCERTAIN | DISPROVEN | OUTDATED
  - confidence: 0 a 1
  - conflicts: textos cortos de tensiones, o lista vacía
  - needs_external_verification: true solo si haría falta una capa más cara (Sol); no la dispares vos
  - reason: una o dos frases

No inventes fuentes. No degradés el suceso: solo resolvé claims.
