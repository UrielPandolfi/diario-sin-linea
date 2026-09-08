"use client";

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import {
  adminJson,
  BODY_SOURCE_LABELS,
  formatWhen,
  labelLookup,
  type AdminDetectionRunsPage,
  type AdminPublicationsPage,
  type AdminSource,
  type AdminSourceItem,
} from "@/lib/admin";

const SELECT_CLASS =
  "mt-1 w-full border border-border bg-background px-3 py-2 font-sans text-sm text-primary";

export default function AdminPublicationsRoute() {
  return (
    <Suspense fallback={<p className="font-sans text-sm text-secondary">Cargando publicaciones…</p>}>
      <AdminPublicationsPage />
    </Suspense>
  );
}

function AdminPublicationsPage() {
  const search = useSearchParams();
  const [view, setView] = useState<"current" | "period">(
    search.get("view") === "period" ? "period" : "current",
  );
  const [page, setPage] = useState<AdminPublicationsPage | null>(null);
  const [period, setPeriod] = useState<AdminDetectionRunsPage | null>(null);
  const [sources, setSources] = useState<AdminSource[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [outcome, setOutcome] = useState(search.get("outcome") || "");
  const [code, setCode] = useState(search.get("code") || "");
  const [sourceId, setSourceId] = useState(search.get("source_id") || "");
  const [unlinked, setUnlinked] = useState(search.get("unlinked") === "1");
  const [offset, setOffset] = useState(0);

  const query = useMemo(() => {
    const params = new URLSearchParams();
    params.set("limit", "50");
    params.set("offset", String(offset));
    if (outcome) params.set("outcome", outcome);
    if (code) params.set("code", code);
    if (sourceId) params.set("source_id", sourceId);
    if (unlinked) params.set("unlinked", "true");
    return params.toString();
  }, [code, offset, outcome, sourceId, unlinked]);

  const load = useCallback(async () => {
    setError(null);
    const nextSources = await adminJson<AdminSource[]>("/api/v1/admin/sources");
    setSources(nextSources);
    if (view === "period") {
      const params = new URLSearchParams({ limit: "50", offset: String(offset) });
      if (outcome) params.set("outcome", outcome);
      setPeriod(await adminJson<AdminDetectionRunsPage>(`/api/v1/admin/detection-runs?${params}`));
      setPage(null);
      return;
    }
    setPage(await adminJson<AdminPublicationsPage>(`/api/v1/admin/publications?${query}`));
    setPeriod(null);
  }, [offset, outcome, query, view]);

  useEffect(() => {
    void load().catch((err: unknown) => {
      setError(err instanceof Error ? err.message : "No se pudieron cargar las publicaciones.");
    });
  }, [load]);

  const outcomeEntries =
    page?.outcome_labels != null
      ? Object.entries(page.outcome_labels)
      : Object.entries(period?.by_outcome ?? {}).map(([key, value]) => [key, value.outcome_label]);

  return (
    <main className="space-y-6">
      <div>
        <p className="font-heading text-sm font-medium uppercase tracking-[0.18em] text-accent-ochre">
          Publicaciones
        </p>
        <h1 className="mt-2 font-heading text-3xl font-medium text-primary">Notas ingeridas</h1>
        <p className="mt-2 font-sans text-sm text-secondary">
          El listado muestra el estado actual (última detección). Las estadísticas de período
          cuentan cada corrida.
        </p>
      </div>

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => {
            setView("current");
            setOffset(0);
          }}
          className={`border px-3 py-2 font-sans text-sm ${
            view === "current" ? "border-primary bg-hover text-primary" : "border-border text-secondary"
          }`}
        >
          Estado actual
        </button>
        <button
          type="button"
          onClick={() => {
            setView("period");
            setOffset(0);
          }}
          className={`border px-3 py-2 font-sans text-sm ${
            view === "period" ? "border-primary bg-hover text-primary" : "border-border text-secondary"
          }`}
        >
          Ejecuciones (24 h)
        </button>
      </div>

      <form
        className="grid gap-3 border border-border bg-surface p-4 sm:grid-cols-2 lg:grid-cols-4"
        onSubmit={(event) => {
          event.preventDefault();
          setOffset(0);
          void load();
        }}
      >
        <label className="font-sans text-xs uppercase tracking-[0.12em] text-secondary">
          Resultado
          <select
            className={SELECT_CLASS}
            value={outcome}
            onChange={(event) => {
              setOutcome(event.target.value);
              setOffset(0);
            }}
          >
            <option value="">Todos</option>
            {outcomeEntries.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        {view === "current" ? (
          <>
            <label className="font-sans text-xs uppercase tracking-[0.12em] text-secondary">
              Código
              <input
                className={SELECT_CLASS}
                value={code}
                onChange={(event) => setCode(event.target.value)}
                placeholder="SPORTS_ONLY"
              />
            </label>
            <label className="font-sans text-xs uppercase tracking-[0.12em] text-secondary">
              Fuente
              <select
                className={SELECT_CLASS}
                value={sourceId}
                onChange={(event) => {
                  setSourceId(event.target.value);
                  setOffset(0);
                }}
              >
                <option value="">Todas</option>
                {sources.map((source) => (
                  <option key={source.id} value={source.id}>
                    {source.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex items-end gap-2 font-sans text-sm text-primary">
              <input
                type="checkbox"
                checked={unlinked}
                onChange={(event) => {
                  setUnlinked(event.target.checked);
                  setOffset(0);
                }}
              />
              Sin suceso vinculado
            </label>
          </>
        ) : null}
      </form>

      {error ? <p className="font-sans text-sm text-accent-ochre">{error}</p> : null}

      {view === "current" && page ? (
        <>
          <p className="font-sans text-xs text-secondary">
            Fecha del listado: {page.timestamp_label} ({page.timestamp_field}). {page.total}{" "}
            publicaciones.
            {page.truncated ? " El filtro de resultado se aplicó sobre las 500 más recientes." : ""}
          </p>
          <PublicationList items={page.items} />
          <Pager
            offset={offset}
            limit={page.limit}
            total={page.total}
            onPrev={() => setOffset(Math.max(0, offset - page.limit))}
            onNext={() => setOffset(offset + page.limit)}
          />
        </>
      ) : null}

      {view === "period" && period ? (
        <>
          <p className="font-sans text-xs text-secondary">
            {period.timestamp_label} ({period.timestamp_field}). Intentos {period.attempts} ·
            fuentes únicas {period.unique_items}.
          </p>
          <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {Object.entries(period.by_outcome).map(([key, bucket]) => (
              <button
                key={key}
                type="button"
                onClick={() => {
                  setOutcome(key);
                  setOffset(0);
                }}
                className="border border-border bg-surface p-4 text-left"
              >
                <p className="font-sans text-xs uppercase tracking-[0.12em] text-secondary">
                  {bucket.outcome_label}
                </p>
                <p className="mt-2 font-heading text-2xl text-primary">{bucket.count}</p>
              </button>
            ))}
          </section>
          <ul className="divide-y divide-border border border-border bg-surface">
            {period.runs.map((run) => (
              <li key={run.id} className="px-4 py-3">
                <p className="font-sans text-primary">
                  {run.detection?.outcome_label || run.status} · {run.detection?.code_label || run.stage}
                </p>
                <p className="mt-1 font-sans text-xs text-secondary">
                  intento {run.attempt}
                  {run.trigger ? ` · ${run.trigger}` : ""} · {formatWhen(run.finished_at || run.started_at)}
                  {run.source_item_id ? (
                    <>
                      {" · "}
                      <Link href={`/admin/publications/${run.source_item_id}`} className="text-accent-blue">
                        ver publicación
                      </Link>
                    </>
                  ) : null}
                </p>
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </main>
  );
}

function PublicationList({ items }: { items: AdminSourceItem[] }) {
  if (items.length === 0) {
    return <p className="font-sans text-sm text-secondary">No hay publicaciones con esos filtros.</p>;
  }
  return (
    <ul className="divide-y divide-border border border-border bg-surface">
      {items.map((item) => (
        <li key={item.id} className="px-4 py-3">
          <Link href={`/admin/publications/${item.id}`} className="font-sans text-primary">
            {item.title || item.canonical_url || item.url}
          </Link>
          <p className="mt-1 font-sans text-xs text-secondary">
            {item.outcome_label || item.processing_status}
            {item.code_label ? ` · ${item.code_label}` : ""}
            {item.source_name ? ` · ${item.source_name}` : ""}
            {` · ${labelLookup(BODY_SOURCE_LABELS, item.body_source)}`}
            {` · detectado ${formatWhen(item.detected_at)}`}
          </p>
          {(item.event_ids?.length ?? 0) > 0 ? (
            <p className="mt-1 font-sans text-xs text-secondary">
              Sucesos:{" "}
              {item.event_ids?.map((eventId, index) => (
                <span key={eventId}>
                  {index > 0 ? ", " : ""}
                  <Link href={`/admin/events/${eventId}`} className="text-accent-blue">
                    {eventId.slice(0, 8)}
                  </Link>
                </span>
              ))}
            </p>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

function Pager({
  offset,
  limit,
  total,
  onPrev,
  onNext,
}: {
  offset: number;
  limit: number;
  total: number;
  onPrev: () => void;
  onNext: () => void;
}) {
  return (
    <div className="flex items-center justify-between font-sans text-sm">
      <button
        type="button"
        onClick={onPrev}
        disabled={offset <= 0}
        className="border border-border px-3 py-1 text-primary disabled:opacity-40"
      >
        Anterior
      </button>
      <span className="text-secondary">
        {offset + 1}–{Math.min(offset + limit, total)} de {total}
      </span>
      <button
        type="button"
        onClick={onNext}
        disabled={offset + limit >= total}
        className="border border-border px-3 py-1 text-primary disabled:opacity-40"
      >
        Siguiente
      </button>
    </div>
  );
}
