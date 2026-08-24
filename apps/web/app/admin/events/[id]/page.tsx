"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { adminFetch, adminJson, formatWhen, type AdminEventDetail } from "@/lib/admin";

export default function AdminEventDetailPage() {
  const params = useParams<{ id: string }>();
  const [event, setEvent] = useState<AdminEventDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [researching, setResearching] = useState(false);
  const [resolvingClaims, setResolvingClaims] = useState(false);

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
            {event.locality ? ` · ${event.locality}` : ""}
            {event.neighborhood ? ` · ${event.neighborhood}` : ""}
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
                    </p>
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
                    </p>
                    <p className="mt-1 font-sans text-xs text-secondary">
                      intento {run.attempt} · {formatWhen(run.started_at)}
                      {run.error_message ? ` · ${run.error_message}` : ""}
                    </p>
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
