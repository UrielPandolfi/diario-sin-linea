"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  adminJson,
  formatWhen,
  type AdminSource,
  type AdminSourceItem,
  type AdminStats,
} from "@/lib/admin";

export default function AdminDashboardPage() {
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [items, setItems] = useState<AdminSourceItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [polling, setPolling] = useState(false);
  const [requeuing, setRequeuing] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    const [nextStats, nextItems] = await Promise.all([
      adminJson<AdminStats>("/api/v1/admin/stats"),
      adminJson<AdminSourceItem[]>("/api/v1/admin/source-items?limit=20"),
    ]);
    setStats(nextStats);
    setItems(nextItems);
  }, []);

  useEffect(() => {
    void load().catch((err: unknown) => {
      setError(err instanceof Error ? err.message : "No se pudo cargar el tablero.");
    });
  }, [load]);

  async function pollMonitored() {
    setPolling(true);
    setNotice(null);
    setError(null);
    try {
      const sources = await adminJson<AdminSource[]>("/api/v1/admin/sources");
      const watched = sources.filter((source) => source.is_monitored && source.is_enabled);
      await Promise.all(
        watched.map((source) =>
          adminJson(`/api/v1/admin/sources/${source.id}/poll`, { method: "POST" }),
        ),
      );
      setNotice(
        watched.length
          ? `Poll encolado para ${watched.length} fuente${watched.length === 1 ? "" : "s"} vigilada${watched.length === 1 ? "" : "s"}.`
          : "No hay fuentes vigiladas y habilitadas.",
      );
      await load();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "No se pudo encolar el poll.");
    } finally {
      setPolling(false);
    }
  }

  async function requeuePending() {
    setRequeuing(true);
    setNotice(null);
    setError(null);
    try {
      const result = await adminJson<{ queued: number }>("/api/v1/admin/source-items/requeue-pending?limit=3", {
        method: "POST",
      });
      setNotice(
        result.queued
          ? `Detección encolada para ${result.queued} ítem${result.queued === 1 ? "" : "s"} PENDING. El pipeline de IA arranca en el worker.`
          : "No hay ítems PENDING para reprocesar.",
      );
      await load();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "No se pudo reencolar PENDING.");
    } finally {
      setRequeuing(false);
    }
  }

  return (
    <main className="space-y-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="font-heading text-sm font-medium uppercase tracking-[0.18em] text-accent-ochre">
            Tablero
          </p>
          <h1 className="mt-2 font-heading text-3xl font-medium text-primary">Redacción</h1>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => void requeuePending()}
            disabled={requeuing}
            className="border border-border bg-hover px-3 py-2 font-sans text-sm text-primary disabled:opacity-60"
          >
            {requeuing ? "Encolando…" : "Reprocesar PENDING (3)"}
          </button>
          <button
            type="button"
            onClick={() => void pollMonitored()}
            disabled={polling}
            className="border border-border bg-hover px-3 py-2 font-sans text-sm text-primary disabled:opacity-60"
          >
            {polling ? "Encolando…" : "Poll de vigiladas"}
          </button>
        </div>
      </div>

      {error ? <p className="font-sans text-sm text-accent-ochre">{error}</p> : null}
      {notice ? <p className="font-sans text-sm text-accent-blue">{notice}</p> : null}

      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Fuentes vigiladas" value={stats?.monitored_sources} />
        <StatCard label="Ítems (24 h)" value={stats?.source_items_24h} />
        <StatCard label="Sucesos (24 h)" value={stats?.events_24h} />
        <StatCard label="Corridas fallidas (24 h)" value={stats?.failed_runs_24h} />
      </section>

      <section className="border border-border bg-surface">
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <h2 className="font-heading text-lg text-primary">Ítems recientes</h2>
          <Link href="/admin/sources" className="font-sans text-sm text-secondary">
            Fuentes
          </Link>
        </div>
        {items.length === 0 ? (
          <p className="px-4 py-6 font-sans text-sm text-secondary">Todavía no hay SourceItems.</p>
        ) : (
          <ul className="divide-y divide-border">
            {items.map((item) => (
              <li key={item.id} className="px-4 py-3">
                <p className="font-sans text-primary">{item.title || item.canonical_url || item.url}</p>
                <p className="mt-1 font-sans text-xs text-secondary">
                  {item.processing_status} · {formatWhen(item.detected_at)}
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}

function StatCard({ label, value }: { label: string; value: number | undefined }) {
  return (
    <div className="border border-border bg-surface p-4">
      <p className="font-sans text-xs uppercase tracking-[0.12em] text-secondary">{label}</p>
      <p className="mt-2 font-heading text-2xl text-primary">{value ?? "—"}</p>
    </div>
  );
}
