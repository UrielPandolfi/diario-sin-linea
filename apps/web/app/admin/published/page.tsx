"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { AdminEventList } from "@/components/admin-event-list";
import { adminJson, isPublishedEvent, type AdminEvent } from "@/lib/admin";

export default function AdminPublishedPage() {
  const [events, setEvents] = useState<AdminEvent[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    setEvents(await adminJson<AdminEvent[]>("/api/v1/admin/events?limit=100"));
  }, []);

  useEffect(() => {
    void load().catch((err: unknown) => {
      setError(err instanceof Error ? err.message : "No se pudieron cargar las noticias.");
    });
  }, [load]);

  const published = useMemo(() => events.filter(isPublishedEvent), [events]);
  const unpublished = useMemo(() => events.filter((event) => !isPublishedEvent(event)), [events]);

  return (
    <main className="space-y-8">
      <div>
        <p className="font-heading text-sm font-medium uppercase tracking-[0.18em] text-accent-ochre">
          Publicadas
        </p>
        <h1 className="mt-2 font-heading text-3xl font-medium text-primary">Qué salió y qué no</h1>
        <p className="mt-2 font-sans text-sm text-secondary">
          Mismo recorte que Sucesos (hasta 100). A la izquierda las que llegaron a publicado; a la
          derecha el resto.
        </p>
      </div>

      {error ? <p className="font-sans text-sm text-accent-ochre">{error}</p> : null}

      <div className="grid gap-6 md:grid-cols-2">
        <section className="border border-border bg-surface">
          <header className="border-b border-border px-4 py-3">
            <p className="font-heading text-sm text-primary">Pasaron</p>
            <p className="mt-1 font-sans text-xs text-secondary">
              {published.length} publicada{published.length === 1 ? "" : "s"}
            </p>
          </header>
          <AdminEventList events={published} empty="Todavía no hay notas publicadas en este recorte." />
        </section>

        <section className="border border-border bg-surface">
          <header className="border-b border-border px-4 py-3">
            <p className="font-heading text-sm text-primary">No pasaron</p>
            <p className="mt-1 font-sans text-xs text-secondary">
              {unpublished.length} sin publicar · detectadas, en proceso, fallidas o archivadas
            </p>
          </header>
          <AdminEventList
            events={unpublished}
            empty="Ningún suceso de este recorte quedó sin publicar."
          />
        </section>
      </div>
    </main>
  );
}
