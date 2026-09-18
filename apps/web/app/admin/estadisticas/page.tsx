"use client";

import { useCallback, useEffect, useState } from "react";
import { adminJson, type AdminAnalytics } from "@/lib/admin";

const WINDOWS = [
  { id: "24h", label: "Últimas 24 h" },
  { id: "7d", label: "Últimos 7 días" },
  { id: "all", label: "Todo" },
] as const;

export default function AdminAnalyticsPage() {
  const [windowId, setWindowId] = useState<(typeof WINDOWS)[number]["id"]>("all");
  const [data, setData] = useState<AdminAnalytics | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async (nextWindow: string) => {
    setLoading(true);
    setError(null);
    try {
      setData(await adminJson<AdminAnalytics>(`/api/v1/admin/analytics?window=${nextWindow}`));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "No se pudieron cargar las estadísticas.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(windowId);
  }, [load, windowId]);

  return (
    <main className="space-y-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="font-heading text-sm font-medium uppercase tracking-[0.18em] text-accent-ochre">
            Estadísticas
          </p>
          <h1 className="mt-2 font-heading text-3xl font-medium text-primary">Qué hizo la redacción</h1>
          <p className="mt-2 max-w-2xl font-sans text-sm text-secondary">
            Solo lectura sobre datos ya persistidos. No dispara el pipeline. Pensado para contar el
            trabajo editorial frente a un canal: cuántas notas se leyeron, cuáles no calificaban,
            cuáles se publicaron y qué etiquetas quedaron.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {WINDOWS.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => setWindowId(item.id)}
              className={
                item.id === windowId
                  ? "border border-primary bg-hover px-3 py-2 font-sans text-sm text-primary"
                  : "border border-border bg-hover px-3 py-2 font-sans text-sm text-secondary"
              }
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>

      {error ? <p className="font-sans text-sm text-accent-ochre">{error}</p> : null}
      {loading && data == null ? <p className="font-sans text-sm text-secondary">Cargando…</p> : null}

      {data ? (
        <>
          <section className="border border-border bg-surface p-5">
            <h2 className="font-heading text-lg text-primary">Para presentar</h2>
            <ul className="mt-3 space-y-2">
              {data.headline.map((line) => (
                <li key={line} className="font-sans text-base text-primary">
                  {line}
                </li>
              ))}
            </ul>
            {data.detection.truncated ? (
              <p className="mt-3 font-sans text-xs text-secondary">
                El desglose de detección se recortó al tope de corridas leídas; los totales de
                intentos siguen completos.
              </p>
            ) : null}
          </section>

          <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard label="Notas leídas" value={data.funnel.notes_ingested} />
            <StatCard label="No calificaban" value={data.funnel.notes_discarded_not_news} />
            <StatCard label="Publicadas" value={data.funnel.articles_published} />
            <StatCard label="Actualizadas (Track B)" value={data.funnel.articles_updated_track_b} />
          </section>

          <section className="grid gap-3 lg:grid-cols-2">
            <CountList
              title="Detección (por resultado)"
              empty="Todavía no hay corridas de detección."
              rows={Object.entries(data.detection.by_outcome).map(([key, bucket]) => ({
                key,
                label: bucket.outcome_label,
                count: bucket.unique_items ?? bucket.count,
                hint: `${bucket.count} intentos`,
              }))}
            />
            <CountList
              title="Por qué no calificaban"
              empty="Ninguna nota descartada por alcance editorial."
              rows={data.detection.discarded_codes.map((row) => ({
                key: row.code || row.key,
                label: row.code_label || row.label || row.key,
                count: row.unique_items ?? row.count,
              }))}
            />
          </section>

          <section className="grid gap-3 lg:grid-cols-2">
            <CountList
              title="Etiquetas en notas publicadas"
              empty="Aún no hay notas publicadas para etiquetar."
              rows={data.editorial_labels.on_articles.map((row) => ({
                key: row.key,
                label: row.label || row.key,
                count: row.count,
              }))}
            />
            <CountList
              title="Estado de claims (en publicadas)"
              empty="Sin claims en notas publicadas."
              rows={data.claims.by_status.map((row) => ({
                key: row.key,
                label: row.label || row.key,
                count: row.count,
              }))}
            />
          </section>

          <section className="grid gap-3 lg:grid-cols-2">
            <CountList
              title="Track B / cambio material"
              empty="Sin corridas de escritura en esta ventana."
              rows={[
                {
                  key: "updated",
                  label: "Notas publicadas en v2 o más",
                  count: data.publication.updated_track_b,
                },
                {
                  key: "material",
                  label: "Escrituras con cambio material",
                  count: data.publication.writing_material_updates,
                },
                {
                  key: "no_material",
                  label: "Escrituras sin cambio material",
                  count: data.publication.writing_no_material_change,
                },
                ...data.publication.material_reasons.map((row) => ({
                  key: row.key,
                  label: `Motivo: ${row.key}`,
                  count: row.count,
                })),
              ]}
            />
            <CountList
              title="Fuentes adjuntadas a sucesos"
              empty="Todavía no hay EventSource."
              rows={data.sources.by_relation.map((row) => ({
                key: row.key,
                label: row.label || row.key,
                count: row.count,
              }))}
            />
          </section>
        </>
      ) : null}
    </main>
  );
}

function StatCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="border border-border bg-surface p-4">
      <p className="font-sans text-xs uppercase tracking-[0.12em] text-secondary">{label}</p>
      <p className="mt-2 font-heading text-2xl text-primary">{value}</p>
    </div>
  );
}

function CountList({
  title,
  empty,
  rows,
}: {
  title: string;
  empty: string;
  rows: { key: string; label: string; count: number; hint?: string }[];
}) {
  const visible = rows.filter((row) => row.count > 0);
  return (
    <section className="border border-border bg-surface">
      <h2 className="border-b border-border px-4 py-3 font-heading text-lg text-primary">{title}</h2>
      {visible.length === 0 ? (
        <p className="px-4 py-6 font-sans text-sm text-secondary">{empty}</p>
      ) : (
        <ul className="divide-y divide-border">
          {visible.map((row) => (
            <li key={row.key} className="flex justify-between gap-3 px-4 py-2 font-sans text-sm text-primary">
              <span>
                {row.label}
                {row.hint ? <span className="text-secondary"> · {row.hint}</span> : null}
              </span>
              <span>{row.count}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
