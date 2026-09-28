"use client";

import { EventCard } from "@/features/feed/event-card";
import { FeedEmpty, FeedError, FeedSkeleton } from "@/features/feed/feed-states";
import { safeReturnTo } from "@/lib/auth/return-to";
import { PublicApiError, fetchFeed, fetchLive, fetchLocal, fetchSaved } from "@/lib/api/public";
import type { EventCard as EventCardType, FeedScope } from "@/lib/api/types";
import { useCallback, useEffect, useRef, useState } from "react";

type Kind = FeedScope | "live" | "principal" | "latest" | "saved";

async function loadPage(
  kind: Kind,
  locality: string | undefined,
  cursor: string | null,
): Promise<{ items: EventCardType[]; next_cursor: string | null }> {
  if (kind === "live") return fetchLive({ cursor });
  if (kind === "saved") return fetchSaved({ cursor });
  if (kind === "local") {
    if (!locality) return { items: [], next_cursor: null };
    return fetchLocal({ locality, cursor });
  }
  if (kind === "principal" || kind === "latest") {
    return fetchFeed({ sort: kind, locality, cursor });
  }
  return fetchFeed({ scope: kind, locality, cursor });
}

export function FeedList({
  kind,
  locality,
  emptyTitle,
  emptyDescription,
}: {
  kind: Kind;
  locality?: string;
  emptyTitle: string;
  emptyDescription?: string;
}) {
  const [items, setItems] = useState<EventCardType[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState(false);
  const sentinel = useRef<HTMLDivElement>(null);
  const loadingMoreRef = useRef(false);
  const request = useRef(0);

  const refresh = useCallback(async () => {
    const current = ++request.current;
    setLoading(true);
    setCursor(null);
    setError(false);
    const gated = kind === "principal" || kind === "latest" || kind === "saved" || kind === "main" || kind === "argentina";
    let redirecting = false;
    try {
      const page = await loadPage(kind, locality, null);
      if (current !== request.current) return;
      setItems(page.items);
      setCursor(page.next_cursor);
    } catch (error) {
      if (current !== request.current) return;
      if (gated && error instanceof PublicApiError && error.status === 401) {
        redirecting = true;
        setItems([]);
        const next = safeReturnTo(`${window.location.pathname}${window.location.search}`, "/");
        window.location.assign(`/entrar?next=${encodeURIComponent(next)}`);
        return;
      }
      setError(true);
      setItems([]);
    } finally {
      if (current === request.current && !redirecting) setLoading(false);
    }
  }, [kind, locality]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!cursor || loading || error) return;
    const node = sentinel.current;
    if (!node) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (!entries[0]?.isIntersecting || loadingMoreRef.current) return;
        loadingMoreRef.current = true;
        setLoadingMore(true);
        void loadPage(kind, locality, cursor)
          .then((page) => {
            setItems((current) => {
              const seen = new Set(current.map((item) => item.public_id));
              return [...current, ...page.items.filter((item) => !seen.has(item.public_id))];
            });
            setCursor(page.next_cursor);
          })
          .catch((error: unknown) => {
            if (error instanceof PublicApiError && error.status === 401) {
              setItems([]);
              setCursor(null);
              const next = safeReturnTo(`${window.location.pathname}${window.location.search}`, "/");
              window.location.assign(`/entrar?next=${encodeURIComponent(next)}`);
            }
          })
          .finally(() => {
            loadingMoreRef.current = false;
            setLoadingMore(false);
          });
      },
      { rootMargin: "240px" },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [cursor, kind, locality, loading, error]);

  if (loading) return <FeedSkeleton />;
  if (error) return <FeedError onRetry={() => void refresh()} />;
  if (items.length === 0) return <FeedEmpty title={emptyTitle} description={emptyDescription} />;

  return (
    <div>
      {items.map((item) => (
        <EventCard
          key={item.public_id}
          item={item}
          onSavedChange={
            kind === "saved"
              ? (saved) => {
                  if (!saved) setItems((current) => current.filter((row) => row.public_id !== item.public_id));
                }
              : undefined
          }
        />
      ))}
      {cursor ? <div ref={sentinel} className="h-8" /> : null}
      {loadingMore ? <FeedSkeleton rows={2} /> : null}
    </div>
  );
}
