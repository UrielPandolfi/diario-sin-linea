# Handoff

**Fecha:** 2026-09-28

**Tarea:** Validar en base de test la reescritura acotada y, sobre la base operativa, auditar la candidata vigente de cada artículo. Publicar solo lo que aprueba. Sin commit. Beat no se arrancó. `AUTO_PUBLISH` sigue en `false`.

## Resultado

Pytest en la imagen de API, contra `sin_linea_test`: 100 pruebas de audit, publish, superficies, certeza y trazabilidad. Las dos que leen el export pasan si el archivo está montado. La política no relaja el tope ni `published_version`.

Corrida real por el worker, una candidata por artículo. Publicados: Formosa `fe26e42b` v2 (1 reescritura), triple crimen `88184369` v1, Esteche `78638d2c` v1, La Tablada `fa0fa66a` v3. Siguen en la versión pública anterior: resolución AMIA `b8343be8` v2 y Rafecas `a3dc7124` v2. Sin publicar: Milei por cobertura y vigencia, Cristina por contrato incompleto junto con atribución, Formosa Gran Guardia `ab70f815` por central sin verificar.

## Pendiente

Beat no está en marcha; su configuración no se cambió. No hay artículos ya publicados sin candidata pendiente.
