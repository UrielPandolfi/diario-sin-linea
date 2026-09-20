"use client";

import { useEffect, useMemo, useState } from "react";
import { adminJson, type AdminEventDetail, type AdminVersionTrace } from "@/lib/admin";

const MEANING_COPY: Record<string, string> = {
  produced_this_version: "produjo el texto de esta versión",
  context_only: "aportó contexto; no produjo este texto",
  not_recorded: "no registrado",
};

function Field({ label, value }: { label: string; value: string | number | null | undefined }) {
  return (
    <p className="font-sans text-sm text-primary">
      <span className="text-secondary">{label}: </span>
      {value == null || value === "" ? "—" : String(value)}
    </p>
  );
}

export function VersionTracePanel({ detail }: { detail: AdminEventDetail }) {
  const article = detail.article;
  const versions = article?.versions ?? [];
  const defaultVersion = article?.published_version ?? article?.current_version ?? null;
  const [selected, setSelected] = useState<number | null>(defaultVersion);
  const [trace, setTrace] = useState<AdminVersionTrace | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setSelected(article?.published_version ?? article?.current_version ?? null);
  }, [article?.id, article?.published_version, article?.current_version]);

  useEffect(() => {
    if (!article?.id || selected == null) {
      setTrace(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    adminJson<AdminVersionTrace>(`/api/v1/admin/articles/${article.id}/versions/${selected}/trace`)
      .then((payload) => {
        if (!cancelled) setTrace(payload);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setTrace(null);
          setError(err instanceof Error ? err.message : "No se pudo cargar la trazabilidad.");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [article?.id, selected]);

  const options = useMemo(() => {
    if (versions.length > 0) return versions;
    if (article == null) return [];
    return [
      {
        id: article.id,
        version_number: article.current_version,
        change_reason: null,
        published_at: article.published_at,
        created_at: null,
      },
    ];
  }, [versions, article]);

  if (!article) {
    return (
      <section className="border border-border bg-surface">
        <h2 className="border-b border-border px-4 py-3 font-heading text-lg text-primary">
          Trazabilidad de versión
        </h2>
        <p className="px-4 py-6 font-sans text-sm text-secondary">Sin artículo para exportar.</p>
      </section>
    );
  }

  function download() {
    if (!trace) return;
    const blob = new Blob([JSON.stringify(trace, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `article-${trace.article_id}-v${trace.article_version}-trace.json`;
    link.click();
    URL.revokeObjectURL(url);
  }

  return (
    <section className="border border-border bg-surface">
      <h2 className="border-b border-border px-4 py-3 font-heading text-lg text-primary">
        Trazabilidad de versión
      </h2>
      <div className="space-y-3 px-4 py-4">
        <p className="font-sans text-sm text-secondary">
          Esta sección lee el snapshot atado a la versión elegida. La tabla de claims de más
          arriba es el estado live del suceso; no sustituye a esta cadena.
        </p>
        {article.published_version == null ? (
          <p className="font-sans text-sm text-accent-ochre">
            No hay versión publicada. El selector muestra un borrador; no se exporta como live.
          </p>
        ) : null}
        <label className="block font-sans text-sm text-primary">
          Versión
          <select
            className="mt-1 block w-full border border-border bg-background px-2 py-1"
            value={selected ?? ""}
            onChange={(event) => setSelected(Number(event.target.value))}
          >
            {options.map((row) => (
              <option key={row.id} value={row.version_number}>
                v{row.version_number}
                {article.published_version === row.version_number ? " · publicada" : ""}
                {article.current_version === row.version_number ? " · current" : ""}
                {row.change_reason ? ` · ${row.change_reason}` : ""}
              </option>
            ))}
          </select>
        </label>
        {loading ? <p className="font-sans text-sm text-secondary">Cargando…</p> : null}
        {error ? <p className="font-sans text-sm text-accent-ochre">{error}</p> : null}
        {trace ? (
          <div className="space-y-1">
            <Field label="article_id" value={trace.article_id} />
            <Field label="event_id" value={trace.event_id} />
            <Field label="article_version" value={trace.article_version} />
            <Field label="article_version_id" value={trace.article_version_id} />
            <Field
              label="writing_run_id"
              value={
                trace.writing_run_id
                  ? `${trace.writing_run_id} (${MEANING_COPY[trace.writing_run_meaning] ?? trace.writing_run_meaning})`
                  : null
              }
            />
            <Field label="verification_run_id" value={trace.verification_run_id} />
            <Field label="coverage_run_id" value={trace.coverage_run_id} />
            <Field label="claims_fingerprint" value={trace.claims_fingerprint} />
            <Field label="contract_version" value={trace.contract_version} />
            <Field label="export_schema" value={trace.export_schema} />
            <Field
              label="current / published"
              value={`${trace.article_pointers.current_version} / ${trace.article_pointers.published_version ?? "—"}`}
            />
            {trace.missing_fields.length > 0 ? (
              <p className="font-sans text-sm text-accent-ochre">
                Campos no registrados: {trace.missing_fields.join(", ")}
              </p>
            ) : null}
            {trace.unresolvable_fields.length > 0 ? (
              <p className="font-sans text-sm text-accent-ochre">
                Referencias no resolubles: {trace.unresolvable_fields.join(", ")}
              </p>
            ) : null}
            {trace.inconsistencies.length > 0 ? (
              <p className="font-sans text-sm text-accent-ochre">
                Inconsistencias:{" "}
                {trace.inconsistencies.map((row) => `${row.field}:${row.detail}`).join(" · ")}
              </p>
            ) : null}
            <button
              type="button"
              className="mt-2 border border-border px-3 py-1 font-sans text-sm text-primary"
              onClick={download}
            >
              Descargar JSON
            </button>
          </div>
        ) : null}
      </div>
    </section>
  );
}
