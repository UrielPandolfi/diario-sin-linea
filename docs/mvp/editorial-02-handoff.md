# Traspaso etapa 2 → 3 (editorial)

Cierre de redacción, auditoría y bloqueo (2026-09-09). Etapa 1 (`editorial-evidence-1`) sigue siendo el contrato de claims/verify. Esta etapa **no** tocó UI Admin ni eval paga.

## Comportamiento efectivo

- Writing congela el contrato **antes** del LLM y lo ata a `article.current_version`. Claims o evidencia posteriores no alteran ese objeto ni aprueban otro texto.
- Audit carga el snapshot de **esa** versión. No llama `build_article_context` sobre claims actuales. Snapshot incompleto o desparejado → `contract_missing` / `contract_unpaired`; no se rellena con el par vigente.
- Invariantes estructurales (código): contrato ausente/inválido/desparejado; `coverage_gap` o `expected_central.match != equivalent`; `central_unverified` o `verification_incomplete` de centrales. Sobreviven a un auditor optimista. Parafrasear o anteponer “según…” **no** cierra el gap. Un secundario diferido no usado **no** bloquea. `SINGLE_SOURCE` evaluado **no** es “no verificado”.
- Semántica (LLM + señales, no HIGH irreversible por un marcador): atribución, vigencia en voz de Sin Línea vs atribuida, plural de corroboración vs primaria auténtica del dicho. `primary_access=not_found` no es veto universal. No se recalcula SUPPORTED/SINGLE_SOURCE. No se re-encola verify desde Audit.
- Rewrite: solo issues no estructurales; mismo snapshot en vN+1; auditoría final propia. Cap 2 → peor caso 3 auditorías + 2 rewrites. Agotar → `passed=false`, DRAFT, live intacto.
- Publish (autónomo y `POST .../publish` admin, incluido override de hold): último auditing **completado**; `passed` de **esta** versión + snapshot. `EditorialService.revise` no pasa por el gate.

## Contrato de findings

`AuditIssue` opcional: `reason`, `claim_ref` / `claim_id`, `action` (`attribute` | `drop` | `rewrite` | `review`). Motivos de máquina en `AuditIssueReason` (`central_uncovered`, `contract_missing`, `contract_unpaired`, `central_unverified`, `unbacked_material`, `norm_effective_as_fact`, `single_as_corroborated`, …). `ArticleAuditResult.editorial_passed` alias de `passed` tras merge. El run guarda `audited`, `technical_ok`, `evidence_snapshot`, `version_after`, `structural_issue_count`.

`attribute` solo si el snapshot prueba que esa fuente dijo o reportó lo afirmado. “Según LN+” sobre un hecho inventado no valida.

## Pendiente (etapa 3)

- Admin UI de `support_basis` y coverage (estado de `expected_central`, gap, presupuesto). Admin ya muestra issues de cap_exhausted; campos extra de findings son opcionales.
- Eval paga (`scripts/run_editorial_eval.py`): **no** corrida. Alcance y costo explícitos antes de correrla (tokens writing + hasta 3 auditorías + 2 rewrites; sin research extra si se siembra el par). No cambiar `AUDITING_MODEL` por esta etapa.
- Track B (detección/link, `no_claims`) sigue en STATE. RELATED_CONTEXT no se adjunta.

## Fuera de esta etapa (sigue fuera)

Migración Alembic, cambiar modelo de Sol, encolar verify desde Audit, publicar, APIs pagas.
