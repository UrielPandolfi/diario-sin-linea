"use client";

import { fetchNearby } from "@/lib/api/public";
import type { EventCard } from "@/lib/api/types";
import { formatRelative } from "@/lib/relative-time";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

export function NearbyPanel({ locality }: { locality: string }) {
  const [items, setItems] = useState<EventCard[]>([]);
  const [error, setError] = useState(false);
  const [now, setNow] = useState(() => Date.now());

  const load = useCallback(async () => {
    try {
      const payload = await fetchNearby(locality, 8);
      setItems(payload.items);
      setError(false);
    } catch {
      setError(true);
    }
  }, [locality]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 30_000);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <section className="border-t border-border px-4 py-4">
      <h2 className="font-heading text-sm font-medium uppercase tracking-[0.16em] text-accent-ochre">Cerca tuyo</h2>
      <p className="mt-1 font-sans text-xs text-muted">{locality}</p>
      {error ? (
        <div className="mt-3">
          <p className="font-sans text-sm text-secondary">No pudimos actualizar esta lista.</p>
          <button type="button" onClick={() => void load()} className="mt-2 text-sm text-primary underline">
            Reintentar
          </button>
        </div>
      ) : items.length === 0 ? (
        <p className="mt-3 font-sans text-sm text-secondary">No hay sucesos recientes cerca de {locality}.</p>
      ) : (
        <ol className="mt-3">
          {items.map((item) => (
            <li key={item.public_id} className="border-b border-border py-3 last:border-b-0">
              <Link href={`/noticias/${item.slug}`} className="block text-primary hover:text-accent-blue">
                <p className="font-sans text-[11px] text-muted">{formatRelative(item.updated_at || item.published_at, now)}</p>
                <p className="mt-1 font-heading text-sm leading-snug">{item.headline}</p>
              </Link>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
