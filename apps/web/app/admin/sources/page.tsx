"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { adminJson, formatWhen, type AdminSource } from "@/lib/admin";

export default function AdminSourcesPage() {
  const [sources, setSources] = useState<AdminSource[]>([]);
  const [name, setName] = useState("");
  const [feedUrl, setFeedUrl] = useState("");
  const [homepageUrl, setHomepageUrl] = useState("");
  const [monitored, setMonitored] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    setSources(await adminJson<AdminSource[]>("/api/v1/admin/sources"));
  }, []);

  useEffect(() => {
    void load().catch((err: unknown) => {
      setError(err instanceof Error ? err.message : "No se pudieron cargar las fuentes.");
    });
  }, [load]);

  async function onCreate(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setNotice(null);
    setError(null);
    try {
      await adminJson<AdminSource>("/api/v1/admin/sources", {
        method: "POST",
        body: JSON.stringify({
          name,
          feed_url: feedUrl,
          homepage_url: homepageUrl || null,
          preferred_ingestion_method: "RSS",
          is_monitored: monitored,
          is_enabled: true,
        }),
      });
      setName("");
      setFeedUrl("");
      setHomepageUrl("");
      setMonitored(true);
      setNotice("Fuente creada.");
      await load();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "No se pudo crear la fuente.");
    } finally {
      setSaving(false);
    }
  }

  async function toggleMonitored(source: AdminSource) {
    setBusyId(source.id);
    setError(null);
    try {
      await adminJson<AdminSource>(`/api/v1/admin/sources/${source.id}`, {
        method: "PATCH",
        body: JSON.stringify({ is_monitored: !source.is_monitored }),
      });
      await load();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "No se pudo actualizar la fuente.");
    } finally {
      setBusyId(null);
    }
  }

  async function poll(source: AdminSource) {
    setBusyId(source.id);
    setNotice(null);
    setError(null);
    try {
      await adminJson(`/api/v1/admin/sources/${source.id}/poll`, { method: "POST" });
      setNotice(`Poll encolado para ${source.name}.`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "No se pudo encolar el poll.");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <main className="space-y-8">
      <div>
        <p className="font-heading text-sm font-medium uppercase tracking-[0.18em] text-accent-ochre">
          Fuentes
        </p>
        <h1 className="mt-2 font-heading text-3xl font-medium text-primary">RSS vigilado</h1>
        <p className="mt-2 font-sans text-secondary">
          Alta RSS, marcar vigilada y poll manual. Beat repite el poll cada 900 s por defecto.
        </p>
      </div>

      {error ? <p className="font-sans text-sm text-accent-ochre">{error}</p> : null}
      {notice ? <p className="font-sans text-sm text-accent-blue">{notice}</p> : null}

      <form onSubmit={onCreate} className="space-y-4 border border-border bg-surface p-5">
        <h2 className="font-heading text-lg text-primary">Nueva fuente RSS</h2>
        <label className="block font-sans text-sm text-secondary">
          Nombre
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            className="mt-1 w-full border border-border bg-background px-3 py-2 font-sans text-primary"
            required
          />
        </label>
        <label className="block font-sans text-sm text-secondary">
          feed_url
          <input
            type="url"
            value={feedUrl}
            onChange={(event) => setFeedUrl(event.target.value)}
            className="mt-1 w-full border border-border bg-background px-3 py-2 font-sans text-primary"
            placeholder="https://ejemplo.test/rss.xml"
            required
          />
        </label>
        <label className="block font-sans text-sm text-secondary">
          homepage_url (opcional)
          <input
            type="url"
            value={homepageUrl}
            onChange={(event) => setHomepageUrl(event.target.value)}
            className="mt-1 w-full border border-border bg-background px-3 py-2 font-sans text-primary"
          />
        </label>
        <label className="flex items-center gap-2 font-sans text-sm text-secondary">
          <input
            type="checkbox"
            checked={monitored}
            onChange={(event) => setMonitored(event.target.checked)}
          />
          Marcar como vigilada
        </label>
        <button
          type="submit"
          disabled={saving}
          className="border border-border bg-hover px-3 py-2 font-sans text-sm text-primary disabled:opacity-60"
        >
          {saving ? "Guardando…" : "Crear fuente"}
        </button>
      </form>

      <section className="border border-border bg-surface">
        <h2 className="border-b border-border px-4 py-3 font-heading text-lg text-primary">Listado</h2>
        {sources.length === 0 ? (
          <p className="px-4 py-6 font-sans text-sm text-secondary">No hay fuentes todavía.</p>
        ) : (
          <ul className="divide-y divide-border">
            {sources.map((source) => (
              <li key={source.id} className="flex flex-wrap items-start justify-between gap-3 px-4 py-4">
                <div>
                  <p className="font-sans text-primary">{source.name}</p>
                  <p className="mt-1 font-sans text-xs text-secondary">
                    {source.preferred_ingestion_method}
                    {source.feed_url ? ` · ${source.feed_url}` : ""}
                    {source.is_monitored ? " · vigilada" : " · no vigilada"}
                    {source.is_enabled ? "" : " · deshabilitada"}
                  </p>
                  <p className="mt-1 font-sans text-xs text-secondary">
                    último ok {formatWhen(source.last_success_at)} · fallo {formatWhen(source.last_failure_at)}
                  </p>
                </div>
                <div className="flex gap-2">
                  <button
                    type="button"
                    disabled={busyId === source.id}
                    onClick={() => void toggleMonitored(source)}
                    className="border border-border bg-hover px-3 py-1.5 font-sans text-sm text-primary disabled:opacity-60"
                  >
                    {source.is_monitored ? "Quitar vigilancia" : "Marcar vigilada"}
                  </button>
                  <button
                    type="button"
                    disabled={busyId === source.id}
                    onClick={() => void poll(source)}
                    className="border border-border bg-hover px-3 py-1.5 font-sans text-sm text-primary disabled:opacity-60"
                  >
                    Poll
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}
