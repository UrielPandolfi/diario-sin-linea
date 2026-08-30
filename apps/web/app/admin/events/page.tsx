"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { AdminEventList } from "@/components/admin-event-list";
import {
  adminJson,
  EVENT_STATUS_LABELS,
  EVENT_STATUS_OPTIONS,
  labelLookup,
  PIPELINE_STAGE_LABELS,
  PIPELINE_STAGE_OPTIONS,
  PIPELINE_STATUS_LABELS,
  PIPELINE_STATUS_OPTIONS,
  uniqueEventValues,
  type AdminEvent,
} from "@/lib/admin";

const SELECT_CLASS =
  "mt-1 w-full border border-border bg-background px-3 py-2 font-sans text-sm text-primary";

type Filters = {
  query: string;
  status: string;
  eventType: string;
  locality: string;
  pipelineStage: string;
  pipelineStatus: string;
};

const EMPTY_FILTERS: Filters = {
  query: "",
  status: "",
  eventType: "",
  locality: "",
  pipelineStage: "",
  pipelineStatus: "",
};

function mergeOptions(known: string[], fromData: string[]): string[] {
  return [...new Set([...known, ...fromData])].sort((a, b) => a.localeCompare(b, "es"));
}

export default function AdminEventsPage() {
  const [events, setEvents] = useState<AdminEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);

  const load = useCallback(async () => {
    setError(null);
    setEvents(await adminJson<AdminEvent[]>("/api/v1/admin/events?limit=100"));
  }, []);

  useEffect(() => {
    void load().catch((err: unknown) => {
      setError(err instanceof Error ? err.message : "No se pudieron cargar los sucesos.");
    });
  }, [load]);

  const eventTypes = useMemo(() => uniqueEventValues(events, "event_type"), [events]);
  const localities = useMemo(() => uniqueEventValues(events, "locality"), [events]);
  const stages = useMemo(
    () => mergeOptions(PIPELINE_STAGE_OPTIONS, uniqueEventValues(events, "pipeline_stage")),
    [events],
  );
  const statuses = useMemo(
    () => mergeOptions(EVENT_STATUS_OPTIONS, uniqueEventValues(events, "status")),
    [events],
  );
  const pipelineStatuses = useMemo(
    () => mergeOptions(PIPELINE_STATUS_OPTIONS, uniqueEventValues(events, "pipeline_run_status")),
    [events],
  );

  const filtered = useMemo(() => {
    const query = filters.query.trim().toLowerCase();
    return events.filter((event) => {
      if (filters.status && event.status !== filters.status) return false;
      if (filters.eventType && event.event_type !== filters.eventType) return false;
      if (filters.locality && event.locality !== filters.locality) return false;
      if (filters.pipelineStage && event.pipeline_stage !== filters.pipelineStage) return false;
      if (filters.pipelineStatus && event.pipeline_run_status !== filters.pipelineStatus) {
        return false;
      }
      if (query) {
        const haystack = [
          event.title_internal,
          event.short_summary,
          event.event_type,
          event.status,
          event.locality,
          event.province,
          event.pipeline_stage,
          event.pipeline_run_status,
        ]
          .filter(Boolean)
          .join(" ")
          .toLowerCase();
        if (!haystack.includes(query)) return false;
      }
      return true;
    });
  }, [events, filters]);

  const filtersActive = useMemo(
    () => Object.values(filters).some((value) => value.trim() !== ""),
    [filters],
  );

  function patchFilter<K extends keyof Filters>(key: K, value: Filters[K]) {
    setFilters((current) => ({ ...current, [key]: value }));
  }

  return (
    <main className="space-y-8">
      <div>
        <p className="font-heading text-sm font-medium uppercase tracking-[0.18em] text-accent-ochre">
          Sucesos
        </p>
        <h1 className="mt-2 font-heading text-3xl font-medium text-primary">Eventos detectados</h1>
      </div>

      {error ? <p className="font-sans text-sm text-accent-ochre">{error}</p> : null}

      <section className="border border-border bg-surface p-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <p className="font-heading text-sm text-primary">Filtros</p>
          {filtersActive ? (
            <button
              type="button"
              onClick={() => setFilters(EMPTY_FILTERS)}
              className="font-sans text-sm text-secondary hover:text-primary"
            >
              Limpiar
            </button>
          ) : null}
        </div>
        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <label className="block font-sans text-sm text-secondary">
            Buscar
            <input
              type="search"
              value={filters.query}
              onChange={(event) => patchFilter("query", event.target.value)}
              placeholder="Título, resumen, tipo…"
              className={SELECT_CLASS}
            />
          </label>
          <label className="block font-sans text-sm text-secondary">
            Estado
            <select
              value={filters.status}
              onChange={(event) => patchFilter("status", event.target.value)}
              className={SELECT_CLASS}
            >
              <option value="">Todos</option>
              {statuses.map((value) => (
                <option key={value} value={value}>
                  {labelLookup(EVENT_STATUS_LABELS, value)}
                </option>
              ))}
            </select>
          </label>
          <label className="block font-sans text-sm text-secondary">
            Tipo
            <select
              value={filters.eventType}
              onChange={(event) => patchFilter("eventType", event.target.value)}
              className={SELECT_CLASS}
            >
              <option value="">Todos</option>
              {eventTypes.map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </label>
          <label className="block font-sans text-sm text-secondary">
            Localidad
            <select
              value={filters.locality}
              onChange={(event) => patchFilter("locality", event.target.value)}
              className={SELECT_CLASS}
            >
              <option value="">Todas</option>
              {localities.map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </label>
          <label className="block font-sans text-sm text-secondary">
            Etapa del pipeline
            <select
              value={filters.pipelineStage}
              onChange={(event) => patchFilter("pipelineStage", event.target.value)}
              className={SELECT_CLASS}
            >
              <option value="">Todas</option>
              {stages.map((value) => (
                <option key={value} value={value}>
                  {labelLookup(PIPELINE_STAGE_LABELS, value)}
                </option>
              ))}
            </select>
          </label>
          <label className="block font-sans text-sm text-secondary">
            Resultado del pipeline
            <select
              value={filters.pipelineStatus}
              onChange={(event) => patchFilter("pipelineStatus", event.target.value)}
              className={SELECT_CLASS}
            >
              <option value="">Todos</option>
              {pipelineStatuses.map((value) => (
                <option key={value} value={value}>
                  {labelLookup(PIPELINE_STATUS_LABELS, value)}
                </option>
              ))}
            </select>
          </label>
        </div>
      </section>

      <section className="border border-border bg-surface">
        <p className="border-b border-border px-4 py-3 font-sans text-xs text-secondary">
          {filtered.length} de {events.length} suceso{events.length === 1 ? "" : "s"}
        </p>
        <AdminEventList
          events={filtered}
          empty={
            events.length === 0
              ? "Todavía no hay Events."
              : "Ningún suceso coincide con esos filtros."
          }
        />
      </section>
    </main>
  );
}
