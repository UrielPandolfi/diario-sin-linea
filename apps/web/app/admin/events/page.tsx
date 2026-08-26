"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { adminJson, formatTokens, formatWhen, type AdminEvent } from "@/lib/admin";

export default function AdminEventsPage() {
  const [events, setEvents] = useState<AdminEvent[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    setEvents(await adminJson<AdminEvent[]>("/api/v1/admin/events?limit=50"));
  }, []);

  useEffect(() => {
    void load().catch((err: unknown) => {
      setError(err instanceof Error ? err.message : "No se pudieron cargar los sucesos.");
    });
  }, [load]);

  return (
    <main className="space-y-8">
      <div>
        <p className="font-heading text-sm font-medium uppercase tracking-[0.18em] text-accent-ochre">
          Sucesos
        </p>
        <h1 className="mt-2 font-heading text-3xl font-medium text-primary">Eventos detectados</h1>
      </div>

      {error ? <p className="font-sans text-sm text-accent-ochre">{error}</p> : null}

      <section className="border border-border bg-surface">
        {events.length === 0 ? (
          <p className="px-4 py-6 font-sans text-sm text-secondary">Todavía no hay Events.</p>
        ) : (
          <ul className="divide-y divide-border">
            {events.map((event) => (
              <li key={event.id}>
                <Link href={`/admin/events/${event.id}`} className="block px-4 py-3 hover:bg-hover">
                  <p className="font-sans text-primary">{event.title_internal}</p>
                  <p className="mt-1 font-sans text-xs text-secondary">
                    {event.event_type} · {event.status}
                    {event.pipeline_stage
                      ? ` · ${event.pipeline_stage}${event.pipeline_run_status ? ` · ${event.pipeline_run_status}` : ""}`
                      : ""}
                    {typeof event.tokens_total === "number" && event.tokens_total > 0
                      ? ` · ${formatTokens(event.tokens_total)} tok`
                      : ""}
                    {event.locality ? ` · ${event.locality}` : ""}
                    {event.province ? `, ${event.province}` : ""} · {formatWhen(event.detected_at)}
                  </p>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}
