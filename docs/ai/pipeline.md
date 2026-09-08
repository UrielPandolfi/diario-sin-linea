# Pipeline conectado

Circuito real en [`apps/api/app/workers/tasks.py`](../../apps/api/app/workers/tasks.py). Rutas de cola en el mismo archivo; Beat: `poll_monitored_sources` cada `ingestion_poll_interval_seconds`. Admin re-encola stages con trigger `"admin"` (`api/admin.py`). Casos de lectores y `EditorialService` **no** están en este circuito.

```mermaid
flowchart LR
  poll[poll_source] --> detect[detect_event]
  detect -->|created| research[research_event]
  detect -->|link_or_skip| stopDetect[no_research]
  research -->|not_skipped| claims[resolve_event_claims]
  claims -->|not_skipped_and_claims| verify[verify_event_claims]
  verify -->|not_skipped_not_error| write[write_event_article]
  write -->|written| audit[audit_event_article]
  audit -->|passed_and_not_hold| publish[publish_event_article]
```

## Etapas

| Task | Cola | Servicio | Siguiente |
| --- | --- | --- | --- |
| `poll_source` | `ingestion` | `IngestionService.poll_source` | `detect_event` por item (cap `max_new_events_per_poll` vía `_item_ids_for_detection`) |
| `detect_event` | `event_detection` | `DetectionService.detect` | `research_event` solo si `created` y `event_id` |
| `research_event` | `research` | `ResearchService.research` | `resolve_event_claims` si no `skipped` |
| `resolve_event_claims` | `claim_resolution` | `ClaimService.resolve` | `verify_event_claims` si no `skipped` y (`persisted` es `None` o `> 0`) |
| `verify_event_claims` | `verification` | `VerificationService.verify` | `write_event_article` si no `skipped` y no `error` |
| `write_event_article` | `writing` | `WritingService.write` | `audit_event_article` si `written is True` |
| `audit_event_article` | `auditing` | `AuditService.audit` | `publish_event_article` si no `skipped`, `passed is True`, y el artículo no tiene `editorial_hold` |
| `publish_event_article` | `publishing` | `PublishService.publish` | — |

Cap de poll: si `allow_new_event_pipeline` falla, `detect_event` persiste un `PipelineRun` de detección con `reason=max_new_events_per_poll` (sin LLM) y retorna skip. Si no crea y `fill_quota`, libera el slot y prueba otro PENDING (`_enqueue_next_for_quota`).

Admin: listado **Publicaciones** (`GET /api/v1/admin/publications`) = estado actual por última detección; `GET /detection-runs` y `stats.detection_24h` cuentan ejecuciones del período (intentos vs fuentes únicas). Costos estimados: `GET /costs` y `stats.costs_24h` (subtotal conocido + cobertura; atribución 1:1). Detalle de suceso: costo directo, sin backfill de embeddings ajenos. `no_material_change` solo en Event/write.

## Create, link, skip (detección)

En `DetectionService._resolve_event` / `detect`: URL conocida → attach; match código/embeddings/Terra → link o create; gate (`evaluate_editorial_gate`, prefiltro deportes) → `SKIPPED`. Create: `EventService.create` + `INITIAL`. **Hoy** solo el create encola research; link/skip no. Eso es cableado, no política documentada a preservar (ver STATE).

Admin puede disparar research/claims/… sobre un Event ya existente; el poll autónomo no reabre esa cadena al vincular un item nuevo.

## Publish

`PublishService`: no archived; `already_published` si `published_version == current_version`; hold bloquea salvo `override_editorial_hold` en admin; exige audit `SUCCESS` `passed` sobre `current_version`. El worker **no lee** `AUTO_PUBLISH`. Ningún stage asigna `READY_FOR_REVIEW`.

## Invariantes (con evidencia en schema/servicios)

- Un `RUNNING` por stage (índices parciales únicos; IntegrityError → `already_running`). Writing/auditing/publishing comparten un lock (`pipeline_lock.py`, migración `0009`).
- Un `Article` por evento; `ArticleVersion` por número; write material sobre publicado deja `DRAFT` y conserva `published_version` live.
- Ingesta: identidad `external_id` o `canonical_url` por fuente; contenido nuevo → `PENDING` otra vez (`SourceItemService.ingest`).
- Claims: unique `claim_id`+`source_item_id` en evidencia; merge por `assertion_key`.
- Issues de Sol en `pipeline_runs.metadata_json`. `Correction` sale de `EditorialService.revise`, no del audit autónomo.
- `editorial_hold` impide el enqueue de publish desde `audit_event_article` (cableado actual; el override no limpia el flag — STATE).
