"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  adminJson,
  BODY_SOURCE_LABELS,
  formatDuration,
  formatWhen,
  labelLookup,
  PIPELINE_STAGE_LABELS,
  PIPELINE_STATUS_LABELS,
  type AdminPublicationDetail,
} from "@/lib/admin";

export default function AdminPublicationDetailPage() {
  const params = useParams<{ id: string }>();
  const [item, setItem] = useState<AdminPublicationDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    setItem(await adminJson<AdminPublicationDetail>(`/api/v1/admin/source-items/${params.id}`));
  }, [params.id]);

  useEffect(() => {
    void load().catch((err: unknown) => {
      setError(err instanceof Error ? err.message : "No se pudo cargar la publicación.");
    });
  }, [load]);

  return (
    <main className="space-y-6">
      <p className="font-sans text-sm">
        <Link href="/admin/publications" className="text-secondary">
          ← Publicaciones
        </Link>
      </p>
      {error ? <p className="font-sans text-sm text-accent-ochre">{error}</p> : null}
      {item ? (
        <>
          <div>
            <p className="font-heading text-sm font-medium uppercase tracking-[0.18em] text-accent-ochre">
              Publicación
            </p>
            <h1 className="mt-2 font-heading text-3xl font-medium text-primary">
              {item.title || item.canonical_url || item.url}
            </h1>
            <p className="mt-2 font-sans text-sm text-secondary">
              {item.outcome_label} · {item.code_label} · {labelLookup(BODY_SOURCE_LABELS, item.body_source)}
            </p>
          </div>
          <section className="border border-border bg-surface p-4 font-sans text-sm text-primary">
            <p>
              <a href={item.url} className="text-accent-blue" target="_blank" rel="noreferrer">
                {item.url}
              </a>
            </p>
            <p className="mt-2 text-xs text-secondary">
              Detectado {formatWhen(item.detected_at)} · publicado por el medio{" "}
              {formatWhen(item.published_at)} · estado {item.processing_status}
              {item.source_name ? ` · ${item.source_name}` : ""}
            </p>
            {(item.event_ids?.length ?? 0) > 0 ? (
              <p className="mt-2 text-xs text-secondary">
                Sucesos vinculados:{" "}
                {item.event_ids?.map((eventId, index) => (
                  <span key={eventId}>
                    {index > 0 ? ", " : ""}
                    <Link href={`/admin/events/${eventId}`} className="text-accent-blue">
                      {eventId.slice(0, 8)}
                    </Link>
                  </span>
                ))}
              </p>
            ) : (
              <p className="mt-2 text-xs text-secondary">Sin sucesos vinculados.</p>
            )}
          </section>
          <section className="border border-border bg-surface">
            <h2 className="border-b border-border px-4 py-3 font-heading text-lg text-primary">
              Historial de corridas
            </h2>
            {item.pipeline_runs.length === 0 ? (
              <p className="px-4 py-6 font-sans text-sm text-secondary">Sin corridas registradas.</p>
            ) : (
              <ul className="divide-y divide-border">
                {item.pipeline_runs.map((run) => (
                  <li key={run.id} className="px-4 py-3">
                    <p className="font-sans text-primary">
                      {labelLookup(PIPELINE_STAGE_LABELS, run.stage)} ·{" "}
                      {labelLookup(PIPELINE_STATUS_LABELS, run.status)}
                      {run.detection ? ` · ${run.detection.outcome_label} (${run.detection.code_label})` : ""}
                      {run.no_material_change ? " · sin cambio material (redacción)" : ""}
                    </p>
                    <p className="mt-1 font-sans text-xs text-secondary">
                      intento {run.attempt}
                      {run.trigger ? ` · ${run.trigger}` : ""} · {formatWhen(run.started_at)}
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
