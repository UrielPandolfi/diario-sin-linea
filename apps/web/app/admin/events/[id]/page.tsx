"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { EditorialReviseForm, HoldOverrideForm } from "@/features/admin/editorial-revise-form";
import { editorialLabelCopy } from "@/features/article/claim-status";
import { adminFetch, adminJson, BODY_SOURCE_LABELS, formatCoverage, formatDuration, formatTokens, formatUsd, formatWhen, labelLookup, type AdminEventDetail } from "@/lib/admin";

export default function AdminEventDetailPage() {
  const params = useParams<{ id: string }>();
  const [event, setEvent] = useState<AdminEventDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [researching, setResearching] = useState(false);
  const [resolvingClaims, setResolvingClaims] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [writing, setWriting] = useState(false);
  const [auditing, setAuditing] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [archiving, setArchiving] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    setEvent(await adminJson<AdminEventDetail>(`/api/v1/admin/events/${params.id}`));
  }, [params.id]);

  async function onResearch() {
    if (!params.id) return;
    setResearching(true);
    setError(null);
    setNotice(null);
    try {
      const response = await adminFetch(`/api/v1/admin/events/${params.id}/research`, {
        method: "POST",
      });
      if (response.status === 409) {
        setNotice("Ya hay una investigación en curso.");
        return;
      }
      if (!response.ok) {
        const detail = await response.text();
        throw new Error(detail || `Error ${response.status}`);
      }
      setNotice("Investigación encolada.");
      await load();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "No se pudo investigar.");
    } finally {
      setResearching(false);
    }
  }

  async function onResolveClaims() {
    if (!params.id) return;
    setResolvingClaims(true);
    setError(null);
    setNotice(null);
    try {
      const response = await adminFetch(`/api/v1/admin/events/${params.id}/claims`, {
        method: "POST",
      });
      if (response.status === 409) {
        setNotice("Ya hay una resolución de claims en curso.");
        return;
      }
      if (!response.ok) {
        const detail = await response.text();
        throw new Error(detail || `Error ${response.status}`);
      }
      setNotice("Resolución de claims encolada.");
      await load();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "No se pudieron resolver los claims.");
    } finally {
      setResolvingClaims(false);
    }
  }

  async function onVerify() {
    if (!params.id) return;
    setVerifying(true);
    setError(null);
    setNotice(null);
    try {
      const response = await adminFetch(`/api/v1/admin/events/${params.id}/verify`, {
        method: "POST",
      });
      if (response.status === 409) {
        setNotice("Ya hay una verificación en curso.");
        return;
      }
      if (!response.ok) {
        const detail = await response.text();
        throw new Error(detail || `Error ${response.status}`);
      }
      setNotice("Verificación encolada.");
      await load();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "No se pudo verificar.");
    } finally {
      setVerifying(false);
    }
  }

  async function onWrite() {
    if (!params.id) return;
    setWriting(true);
    setError(null);
    setNotice(null);
    try {
      const response = await adminFetch(`/api/v1/admin/events/${params.id}/write`, {
        method: "POST",
      });
      if (response.status === 409) {
        setNotice("Ya hay una redacción, auditoría o publicación en curso.");
        return;
      }
      if (!response.ok) {
        const detail = await response.text();
        throw new Error(detail || `Error ${response.status}`);
      }
      setNotice("Redacción encolada.");
      await load();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "No se pudo redactar.");
    } finally {
      setWriting(false);
    }
  }

  async function onAudit() {
    if (!params.id) return;
    setAuditing(true);
    setError(null);
    setNotice(null);
    try {
      const response = await adminFetch(`/api/v1/admin/events/${params.id}/audit`, {
        method: "POST",
      });
      if (response.status === 409) {
        setNotice("Ya hay una redacción, auditoría o publicación en curso.");
        return;
      }
      if (!response.ok) {
        const detail = await response.text();
        throw new Error(detail || `Error ${response.status}`);
      }
      setNotice("Auditoría encolada.");
      await load();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "No se pudo auditar.");
    } finally {
      setAuditing(false);
    }
  }

  async function onPublish() {
    if (!params.id) return;
    setPublishing(true);
    setError(null);
    setNotice(null);
    try {
      const response = await adminFetch(`/api/v1/admin/events/${params.id}/publish`, {
        method: "POST",
      });
      if (response.status === 409) {
        setNotice("No se puede publicar (audit no aprobado o hay un stage en curso).");
        return;
      }
      if (!response.ok) {
        const detail = await response.text();
        throw new Error(detail || `Error ${response.status}`);
      }
      setNotice(response.status === 202 ? "Publicación encolada." : "Ya estaba publicado.");
      await load();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "No se pudo publicar.");
    } finally {
      setPublishing(false);
    }
  }

  async function onArchive() {
    if (!params.id) return;
    setArchiving(true);
    setError(null);
    setNotice(null);
    try {
      const response = await adminFetch(`/api/v1/admin/events/${params.id}/archive`, {
        method: "POST",
      });
      if (response.status === 409) {
        setNotice("Hay un stage en curso.");
        return;
      }
      if (!response.ok) {
        const detail = await response.text();
        throw new Error(detail || `Error ${response.status}`);
      }
      setNotice("Archivado.");
      await load();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "No se pudo archivar.");
    } finally {
      setArchiving(false);
    }
  }

  useEffect(() => {
    if (!params.id) return;
    void load().catch((err: unknown) => {
      setError(err instanceof Error ? err.message : "No se pudo cargar el suceso.");
    });
  }, [load, params.id]);

  return (
    <main className="space-y-8">
      <div>
        <Link href="/admin/events" className="font-sans text-sm text-secondary">
          ← Sucesos
        </Link>
        <p className="mt-3 font-heading text-sm font-medium uppercase tracking-[0.18em] text-accent-ochre">
          Detalle
        </p>
        <h1 className="mt-2 font-heading text-3xl font-medium text-primary">
          {event?.title_internal ?? "Suceso"}
        </h1>
        {event ? (
          <p className="mt-2 font-sans text-secondary">
            {event.event_type} · {event.status}
            {event.pipeline_stage
              ? ` · pipeline ${event.pipeline_stage}${event.pipeline_run_status ? ` · ${event.pipeline_run_status}` : ""}`
              : ""}
            {typeof event.tokens_total === "number"
              ? ` · ${formatTokens(event.tokens_total)} tok`
              : ""}
            {event.locality ? ` · ${event.locality}` : ""}
            {event.neighborhood ? ` · ${event.neighborhood}` : ""}
          </p>
        ) : null}
        {event?.no_material_change ? (
          <p className="mt-2 font-sans text-sm text-secondary">
            Última redacción: sin cambio material (a nivel suceso, no de una fuente).
          </p>
        ) : null}
        {event ? (
          <div className="mt-4 flex flex-wrap gap-2">
            <button
              type="button"
              disabled={researching}
              onClick={() => void onResearch()}
              className="border border-border bg-hover px-3 py-1.5 font-sans text-sm text-primary disabled:opacity-60"
            >
              {researching ? "Investigando…" : "Investigar"}
            </button>
            <button
              type="button"
              disabled={resolvingClaims}
              onClick={() => void onResolveClaims()}
              className="border border-border bg-hover px-3 py-1.5 font-sans text-sm text-primary disabled:opacity-60"
            >
              {resolvingClaims ? "Resolviendo…" : "Resolver claims"}
            </button>
            <button
              type="button"
              disabled={verifying}
              onClick={() => void onVerify()}
              className="border border-border bg-hover px-3 py-1.5 font-sans text-sm text-primary disabled:opacity-60"
            >
              {verifying ? "Verificando…" : "Verificar"}
            </button>
            <button
              type="button"
              disabled={writing}
              onClick={() => void onWrite()}
              className="border border-border bg-hover px-3 py-1.5 font-sans text-sm text-primary disabled:opacity-60"
            >
              {writing ? "Redactando…" : "Redactar"}
            </button>
            <button
              type="button"
              disabled={auditing}
              onClick={() => void onAudit()}
              className="border border-border bg-hover px-3 py-1.5 font-sans text-sm text-primary disabled:opacity-60"
            >
              {auditing ? "Auditando…" : "Auditar"}
            </button>
            <button
              type="button"
              disabled={publishing}
              onClick={() => void onPublish()}
              className="border border-border bg-hover px-3 py-1.5 font-sans text-sm text-primary disabled:opacity-60"
            >
              {publishing ? "Publicando…" : "Publicar (reintento)"}
            </button>
            <button
              type="button"
              disabled={archiving}
              onClick={() => void onArchive()}
              className="border border-border bg-hover px-3 py-1.5 font-sans text-sm text-primary disabled:opacity-60"
            >
              {archiving ? "Archivando…" : "Archivar"}
            </button>
          </div>
        ) : null}
      </div>

      {error ? <p className="font-sans text-sm text-accent-ochre">{error}</p> : null}
      {notice ? <p className="font-sans text-sm text-accent-blue">{notice}</p> : null}

      {event ? (
        <>
          {event.short_summary ? (
            <p className="border border-border bg-surface p-4 font-sans text-sm text-primary">
              {event.short_summary}
            </p>
          ) : null}
          {event.address_text ? (
            <p className="font-sans text-sm text-secondary">{event.address_text}</p>
          ) : null}

          <section className="border border-border bg-surface">
            <h2 className="border-b border-border px-4 py-3 font-heading text-lg text-primary">
              Fuentes
            </h2>
            {event.sources.length === 0 ? (
              <p className="px-4 py-6 font-sans text-sm text-secondary">Sin event_sources.</p>
            ) : (
              <ul className="divide-y divide-border">
                {event.sources.map((link, index) => (
                  <li key={`${link.relation_type}-${index}`} className="px-4 py-3">
                    <p className="font-sans text-primary">
                      {link.source_item?.title || link.source_item?.url || "SourceItem"}
                    </p>
                    <p className="mt-1 font-sans text-xs text-secondary">
                      {link.relation_type}
                      {link.is_primary ? " · primaria" : ""}
                      {link.source_item ? ` · ${link.source_item.processing_status}` : ""}
                      {link.source_item
                        ? ` · ${labelLookup(BODY_SOURCE_LABELS, link.source_item.body_source)}`
                        : ""}
                    </p>
                    {link.source_item ? (
                      <p className="mt-1 font-sans text-xs">
                        <Link href={`/admin/publications/${link.source_item.id}`} className="text-accent-blue">
                          Ver publicación
                        </Link>
                      </p>
                    ) : null}
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="border border-border bg-surface">
            <h2 className="border-b border-border px-4 py-3 font-heading text-lg text-primary">
              Entidades
            </h2>
            {event.entities.length === 0 ? (
              <p className="px-4 py-6 font-sans text-sm text-secondary">Sin event_entities.</p>
            ) : (
              <ul className="divide-y divide-border">
                {event.entities.map((entity) => (
                  <li key={`${entity.id}-${entity.role}`} className="px-4 py-3">
                    <p className="font-sans text-primary">{entity.name ?? entity.id}</p>
                    <p className="mt-1 font-sans text-xs text-secondary">
                      {entity.entity_type ?? "—"} · {entity.role}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="border border-border bg-surface">
            <h2 className="border-b border-border px-4 py-3 font-heading text-lg text-primary">
              Claims
            </h2>
            {(event.claims ?? []).length === 0 ? (
              <p className="px-4 py-6 font-sans text-sm text-secondary">Sin claims.</p>
            ) : (
              <table className="w-full font-sans text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-secondary">
                    <th className="px-4 py-2 font-medium">Claim</th>
                    <th className="px-4 py-2 font-medium">Estado</th>
                    <th className="px-4 py-2 font-medium">Etiquetas</th>
                    <th className="px-4 py-2 font-medium">Importancia</th>
                    <th className="px-4 py-2 font-medium">Fuentes</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {(event.claims ?? []).map((claim) => (
                    <tr
                      key={claim.id}
                      className={claim.status === "CONFLICTING" ? "bg-hover text-accent-ochre" : ""}
                    >
                      <td className="px-4 py-3 text-primary">{claim.canonical_text}</td>
                      <td className="px-4 py-3">{claim.status}</td>
                      <td className="px-4 py-3 text-[11px] uppercase tracking-[0.12em] text-accent-petrol">
                        {(claim.editorial_labels ?? []).map(editorialLabelCopy).join(" · ") || "—"}
                      </td>
                      <td className="px-4 py-3">{claim.importance}</td>
                      <td className="px-4 py-3 text-xs">
                        {claim.evidence
                          .map((row) => `${row.evidence_type}${row.excerpt ? `: ${row.excerpt}` : ""}`)
                          .join(" · ") || "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          {event.audit?.cap_exhausted && event.audit.passed === false ? (
            <section className="border border-border bg-surface">
              <h2 className="border-b border-border px-4 py-3 font-heading text-lg text-accent-ochre">
                Auditoría: ciclo agotado
              </h2>
              <div className="space-y-3 px-4 py-4">
                <p className="font-sans text-sm text-accent-ochre">
                  Sol no aprobó el draft después de {event.audit.rewrite_count ?? 0} rewrites. No
                  se publicó: el borrador sigue en DRAFT y, si ya había una versión live, esa
                  sigue visible.
                </p>
                {event.audit.issues.length > 0 ? (
                  <ul className="space-y-2 font-sans text-sm text-primary">
                    {event.audit.issues.map((issue, index) => (
                      <li key={`${issue.type}-${index}`}>
                        <p>
                          {issue.severity} · {issue.type}: {issue.text}
                        </p>
                        <p className="text-xs text-secondary">{issue.explanation}</p>
                      </li>
                    ))}
                  </ul>
                ) : null}
              </div>
            </section>
          ) : null}

          <section className="border border-border bg-surface">
            <h2 className="border-b border-border px-4 py-3 font-heading text-lg text-primary">
              Borrador
            </h2>
            {event.article ? (
              <div className="space-y-3 px-4 py-4">
                <p className="font-heading text-xl text-primary">{event.article.headline}</p>
                <p className="font-sans text-xs text-secondary">
                  {event.article.status} · versión {event.article.current_version}
                  {event.article.published_version != null
                    ? ` · live v${event.article.published_version}`
                    : ""}
                  {event.article.slug ? ` · ${event.article.slug}` : ""}
                  {event.article.published_at ? ` · publicado ${formatWhen(event.article.published_at)}` : ""}
                </p>
                <p className="font-sans text-sm text-primary">{event.article.summary}</p>
                <div className="whitespace-pre-wrap font-sans text-sm text-primary">{event.article.body}</div>
              </div>
            ) : (
              <p className="px-4 py-6 font-sans text-sm text-secondary">Sin article draft.</p>
            )}
          </section>

          {event.article?.editorial_hold ? (
            <HoldOverrideForm
              eventId={params.id}
              detail={event}
              onDone={(message) => {
                setNotice(message);
                void load();
              }}
            />
          ) : null}

          <section className="border border-border bg-surface">
            <h2 className="border-b border-border px-4 py-3 font-heading text-lg text-primary">
              Revisión editorial
            </h2>
            <EditorialReviseForm
              eventId={params.id}
              detail={event}
              onDone={(message) => {
                setNotice(message);
                void load();
              }}
            />
          </section>

          <section className="border border-border bg-surface">
            <h2 className="border-b border-border px-4 py-3 font-heading text-lg text-primary">
              Tokens y costo directo
            </h2>
            {event.token_usage && event.token_usage.calls > 0 ? (
              <div className="space-y-3 px-4 py-4">
                <p className="font-sans text-sm text-primary">
                  Total {formatTokens(event.token_usage.total_tokens)} · prompt{" "}
                  {formatTokens(event.token_usage.prompt_tokens)} · completion{" "}
                  {formatTokens(event.token_usage.completion_tokens)} ·{" "}
                  {event.token_usage.calls} llamadas
                </p>
                {event.cost ? (
                  <p className="font-sans text-sm text-secondary">
                    Costo directo {formatUsd(event.cost.subtotal_known_usd)} ·{" "}
                    {formatCoverage(event.cost.coverage)}
                    {event.cost.coverage.subtotal_is_total_spend ? "" : " · no es el gasto total"}
                    . El backfill de embeddings de otros sucesos no entra en este total.
                    {event.cost.duration_ms_sum != null
                      ? ` · ${event.cost.duration_ms_sum} ms LLM`
                      : ""}
                  </p>
                ) : null}
                <ul className="divide-y divide-border border border-border">
                  {event.token_usage.by_role_stage.map((row) => (
                    <li
                      key={`${row.model_role}-${row.stage}`}
                      className="flex justify-between px-3 py-2 font-sans text-sm text-primary"
                    >
                      <span>
                        {row.model_role} · {row.stage}
                      </span>
                      <span>
                        {formatTokens(row.total_tokens)} · {row.calls}×
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : (
              <p className="px-4 py-6 font-sans text-sm text-secondary">
                Sin usage registrado (solo corridas posteriores al deploy de telemetría).
              </p>
            )}
          </section>

          <section className="border border-border bg-surface">
            <h2 className="border-b border-border px-4 py-3 font-heading text-lg text-primary">
              pipeline_runs
            </h2>
            {event.pipeline_runs.length === 0 ? (
              <p className="px-4 py-6 font-sans text-sm text-secondary">Sin corridas.</p>
            ) : (
              <ul className="divide-y divide-border">
                {event.pipeline_runs.map((run) => (
                  <li key={run.id} className="px-4 py-3">
                    <p className="font-sans text-primary">
                      {run.stage} · {run.status}
                      {run.no_material_change ? " · sin cambio material" : ""}
                    </p>
                    <p className="mt-1 font-sans text-xs text-secondary">
                      intento {run.attempt} · {formatWhen(run.started_at)}
                      {run.finished_at ? ` → ${formatWhen(run.finished_at)}` : ""}
                      {` · ${formatDuration(run.started_at, run.finished_at)}`}
                      {run.error_message ? ` · ${run.error_message}` : ""}
                    </p>
                    {run.metadata_json && Object.keys(run.metadata_json).length > 0 ? (
                      <pre className="mt-2 overflow-x-auto whitespace-pre-wrap break-all font-mono text-[11px] text-secondary">
                        {JSON.stringify(run.metadata_json, null, 2)}
                      </pre>
                    ) : null}
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      ) : null}
    </main>
  );
}
