"use client";

import { fetchNow } from "@/lib/api/public";
import type { NowItem } from "@/lib/api/types";
import { formatClock } from "@/lib/relative-time";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

export function NowPanel() {
  const [items, setItems] = useState<NowItem[]>([]);
  const [error, setError] = useState(false);

  const load = useCallback(async () => {
    try {
      const payload = await fetchNow(12);
      setItems(payload.items);
      setError(false);
    } catch {
      setError(true);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <section className="px-4 py-4">
      <h2 className="font-heading text-sm font-medium uppercase tracking-[0.16em] text-accent-ochre">Ahora</h2>
      {error ? (
        <div className="mt-3">
          <p className="font-sans text-sm text-secondary">No pudimos actualizar esta lista.</p>
          <button type="button" onClick={() => void load()} className="mt-2 text-sm text-primary underline">
            Reintentar
          </button>
        </div>
      ) : items.length === 0 ? (
        <p className="mt-3 font-sans text-sm text-secondary">Todavía no hay actualizaciones recientes.</p>
      ) : (
        <ol className="mt-3">
          {items.map((item) => (
            <li key={`${item.slug}-${item.occurred_at}`} className="border-b border-border py-3 last:border-b-0">
              <Link href={`/noticias/${item.slug}`} className="block text-primary hover:text-accent-blue">
                <p className="font-sans text-[11px] uppercase tracking-[0.12em] text-muted">
                  {formatClock(item.occurred_at)}
                  {item.locality ? ` · ${item.locality}` : ""}
                </p>
                <p className="mt-1 font-heading text-sm leading-snug">{item.headline}</p>
              </Link>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
