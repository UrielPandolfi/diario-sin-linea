# Handoff

Reemplazar este archivo al cerrar una tarea o al continuar en otro chat. No es un diario de sesiones.

**Fecha:** 2026-09-14

**Tarea:** `event_type` clasifica exclusivamente el suceso principal informado, anclado en `what_happened`, sin exigir que haya ocurrido ahora.

## Objetivo de este chat

Corregir el prompt de Event Extraction y validar su contrato y su comportamiento con el provider real. No derivar el tipo de antecedentes, contexto histórico, delitos de fondo, causas anteriores, biografías ni hechos secundarios. Un homicidio antiguo puede ser el suceso principal; una resolución en una causa por homicidio clasifica el acto judicial.

## Avances

- Único cambio de producto: `apps/api/app/prompts/event_extraction.md`. Primero identifica el asunto concreto en `what_happened`, luego clasifica ese acontecimiento. Tipos ilustrativos y libres; `otro` si no hay seguridad. No inventar un suceso para asignar una categoría.
- Nueve casos nuevos de contrato en `test_prompt_payloads.py`: ancla semántica/exclusiones, antigüedad, descripción factual y ejemplos A–E (más A2: muerte antigua determinada como homicidio).
- Sin cambios en servicios, schemas, modelos, persistencia, deduplicación, gate, research, claims, verification, writing, audit ni frontend. Sin Enum/Literal, migración, backfill ni framework nuevo.
- Prueba manual real mediante `DetectionService(session)._extract_candidate(item)`, con `SourceItem` transitorio y sin llamar a `detect` ni encolar etapas. Se usó la configuración normal de `.env`, sin inyectar providers ni respuestas falsas. DB temporal para tests y registros de consumo; eliminada al terminar.

## Pruebas

Desde `apps/api`, con `DATABASE_URL` apuntando a una base PostgreSQL nueva y separada de la base viva, y Redis disponible:

```bash
python -m pytest tests/test_prompt_payloads.py tests/test_detection.py -q --tb=short
```

**37 passed, 1 warning in 11.04s.** Warning preexistente de Alembic por `path_separator`. Los pytest fijan el contrato del prompt y el cableado con fakes, no prueban la clasificación semántica del modelo real.

## Extracción manual real

2026-09-14 03:19:59 UTC. Fixture: copia de título, URL, fecha y `clean_text` original (2902 caracteres) del SourceItem primario `46398277-f08f-4793-b14b-eb0c3c15d068`, obtenido con conexión de solo lectura. Título: «El búnker K de Cristina: el camporista Mariano Recalde es dueño de un departamento en San José 1111». Sin instrucciones de clasificación añadidas al fixture. El cuerpo habla de propiedad, corrupción y causas judiciales; no contiene la palabra homicidio.

Provider configurado: **OpenAI `gpt-5-nano`**, modelo reportado **`gpt-5-nano-2025-08-07`**, rol `ultra_light_processing`. `extraction_meta={}`: sin fallback a Light (`gpt-4o-mini`). Respuesta con uso reportado: 2728 tokens de entrada, 632 de salida, 3360 totales.

Campos principales del `EventCandidate`, sin editar:

```json
{
  "what_happened": "Mariano Recalde, senador y fundador de La Cámpora, es propietario del departamento 1° A del edificio ubicado en San José 1111, donde Cristina Kirchner cumple prisión domiciliaria; el departamento 1° B fue adquirido por María Soledad Calle, vinculada a La Cámpora, y el departamento 2° D pertenece a Los Sauces S.A., sociedad vinculada a la familia Kirchner.",
  "event_type": "propiedad",
  "short_summary": "Se informó que Mariano Recalde es propietario del departamento 1° A en el edificio de San José 1111, donde Cristina Kirchner cumple prisión domiciliaria; también se mencionan el 1° B adquirido por María Soledad Calle y el 2° D perteneciente a Los Sauces S.A.",
  "editorial_topic": "PUBLIC_ECONOMY"
}
```

**Aceptación satisfecha en esta ejecución:** no es `homicidio`; `what_happened` expresa el asunto concreto; las propiedades y la adquisición mencionadas están en el texto fuente. No inventa una nueva compra, un arresto ni una resolución. `occurred_at=null`. Una muestra real no garantiza todos los casos futuros.

Evidencia local, fuera de CI y de Git: `.editorial-evals/event-type-20260914/{fixture.json,extraction.json,pytest.txt,live-before.json,live-after.json,environment.json}`. `extraction.json` conserva el `EventCandidate` completo, configuración sin secretos, metadata y registros de uso. SHA-256 del prompt validado: `c1dc236059bd76573200a71eb0d0842bd987531331c5a30106c18f014a1a85c8`.

## Comportamiento inesperado y límites

- La primera ejecución quedó bloqueada por la red del sandbox (`WinError 10013`); el reintento con acceso de red completó la extracción real.
- El provider registró un intento sin uso reportado antes de la respuesta exitosa; el registro no conserva la causa. No se cambió la lógica de reintentos ni se sustituyó el modelo.
- El candidato devolvió `locality` como string `"null"`, no JSON null. No disparó fallback (`location_confidence=0.5`).
- `editorial_topic=PUBLIC_ECONOMY` es discutible para un informe sobre patrimonio de actores políticos. `what_happened` no conservó la atribución explícita al Registro de la Propiedad Inmueble. Roles de entidades discutibles: Ercolini como `testigo` no está respaldado por el texto; Los Sauces S.A. salió con `role=organismo`. Estos aspectos se reportan sin ampliar el alcance del cambio.

## Archivos modificados

`apps/api/app/prompts/event_extraction.md`, `apps/api/tests/test_prompt_payloads.py`, `docs/ai/DECISIONS.md`, `docs/ai/STATE.md`, `docs/ai/HANDOFF.md`.

## Siguiente paso

El Event vivo `0ddb9aaa-85c0-4316-8771-67dafa017d86` sigue en `homicidio`, con su embedding existente (1 fila). Snapshot de campos leído antes/después idéntico; no se ejecutó UPDATE ni invalidación/regeneración de embeddings. La corrección manual del tipo y la decisión sobre el embedding quedan para el próximo paso con el usuario; no imponer `otro` automáticamente. El resultado `propiedad` de esta prueba sirve como evidencia para esa revisión, no como backfill.
