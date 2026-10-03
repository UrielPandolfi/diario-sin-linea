"use client";

import { publishedArticlePath } from "@/features/transparency/copy";
import { PublicApiError } from "@/lib/api/public";
import { safeReturnTo } from "@/lib/auth/return-to";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

type DraftCard = {
  id: string;
  headline: string;
  label: string;
  evaluated_at: string;
  reason: string;
  published_path: string | null;
};

function formatEvaluatedAt(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("es-AR", {
    day: "numeric",
    month: "long",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

async function loadDrafts(cursor: string | null): Promise<{ items: DraftCard[]; next_cursor: string | null }> {
  const params = new URLSearchParams();
  if (cursor) params.set("cursor", cursor);
  const path = `/api/v1/transparency/rejected-drafts${params.size ? `?${params}` : ""}`;
  const response = await fetch(path, { credentials: "include", cache: "no-store" });
  if (!response.ok) {
    throw new PublicApiError("request_failed", response.status);
  }
  return (await response.json()) as { items: DraftCard[]; next_cursor: string | null };
}

export function RejectedDraftsList() {
  const [items, setItems] = useState<DraftCard[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      const page = await loadDrafts(null);
      setItems(page.items);
      setCursor(page.next_cursor);
    } catch (caught) {
      if (caught instanceof PublicApiError && caught.status === 401) {
        const next = safeReturnTo(`${window.location.pathname}${window.location.search}`, "/transparencia/borradores");
        window.location.assign(`/entrar?next=${encodeURIComponent(next)}`);
        return;
      }
      setError(true);
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function loadMore() {
    if (!cursor || loadingMore) return;
    setLoadingMore(true);
    try {
      const page = await loadDrafts(cursor);
      setItems((current) => [...current, ...page.items]);
      setCursor(page.next_cursor);
    } catch (caught) {
      if (caught instanceof PublicApiError && caught.status === 401) {
        window.location.assign("/entrar?next=%2Ftransparencia%2Fborradores");
        return;
      }
      setError(true);
    } finally {
      setLoadingMore(false);
    }
  }

  return (
    <div className="mx-auto min-h-screen max-w-measure px-4 py-8 md:px-6">
      <p className="font-sans text-[12px] uppercase tracking-[0.16em] text-accent">Transparencia</p>
      <h1 className="mt-2 font-heading text-3xl font-semibold text-primary">Borradores no aprobados</h1>
      <p className="mt-3 font-sans text-sm leading-relaxed text-secondary">
        Versiones con texto guardado que no superaron la evaluación editorial. No forman parte de las noticias publicadas.
      </p>
      <div className="mt-8 space-y-3">
        {loading ? (
          <div aria-busy="true" aria-live="polite" className="py-6">
            <span className="sr-only">Cargando borradores no aprobados</span>
            <div className="h-16 animate-pulse bg-surface" />
          </div>
        ) : null}
        {!loading && error ? (
          <div className="py-12 text-center">
            <p className="font-heading text-base text-primary">No pudimos cargar los borradores.</p>
            <button type="button" onClick={() => void refresh()} className="mt-4 font-sans text-sm text-accent">
              Reintentar
            </button>
          </div>
        ) : null}
        {!loading && !error && items.length === 0 ? (
          <div className="sl-block px-5 py-16 text-center">
            <p className="font-heading text-lg text-primary">No hay borradores no aprobados</p>
            <p className="mt-2 font-sans text-sm text-secondary">
              Cuando una versión termine la evaluación sin poder publicarse, va a aparecer acá.
            </p>
          </div>
        ) : null}
        {!loading && !error
          ? items.map((item, index) => {
              const published = publishedArticlePath(item.published_path);
              return (
              <article
                key={item.id}
                className="sl-block sl-enter p-5"
                style={{ animationDelay: `${Math.min(index, 8) * 45}ms` }}
              >
                <p className={item.label === "Actualización no aprobada" ? "sl-pill sl-pill-update" : "sl-pill sl-pill-notice"}>
                  {item.label}
                </p>
                <h2 className="mt-2 font-heading text-xl font-semibold text-primary">
                  <Link href={`/transparencia/borradores/${item.id}`} className="text-primary hover:text-accent">
                    {item.headline}
                  </Link>
                </h2>
                <p className="mt-2 font-sans text-[13px] text-secondary">
                  <time dateTime={item.evaluated_at}>Evaluado el {formatEvaluatedAt(item.evaluated_at)}</time>
                </p>
                <p className="mt-2 font-sans text-sm leading-relaxed text-secondary">{item.reason}</p>
                {published ? (
                  <p className="mt-2 font-sans text-sm">
                    <Link href={published}>Ver la versión publicada</Link>
                  </p>
                ) : null}
              </article>
              );
            })
          : null}
        {!loading && !error && cursor ? (
          <button
            type="button"
            onClick={() => void loadMore()}
            disabled={loadingMore}
            className="mt-4 font-sans text-sm text-accent disabled:text-muted"
          >
            {loadingMore ? "Cargando…" : "Cargar más"}
          </button>
        ) : null}
      </div>
    </div>
  );
}
