"use client";

import { EventCard } from "@/features/feed/event-card";
import { FeedEmpty, FeedError, FeedSkeleton } from "@/features/feed/feed-states";
import { fetchFeed, fetchLive, fetchLocal } from "@/lib/api/public";
import type { EventCard as EventCardType, FeedScope } from "@/lib/api/types";
import { useCallback, useEffect, useRef, useState } from "react";

type Kind = FeedScope | "live";

async function loadPage(
  kind: Kind,
  locality: string | undefined,
  cursor: string | null,
): Promise<{ items: EventCardType[]; next_cursor: string | null }> {
  if (kind === "live") return fetchLive({ cursor });
  if (kind === "local") {
    if (!locality) return { items: [], next_cursor: null };
    return fetchLocal({ locality, cursor });
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
  emptyDescription: string;
}) {
  const [items, setItems] = useState<EventCardType[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState(false);
  const sentinel = useRef<HTMLDivElement>(null);
  const loadingMoreRef = useRef(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      const page = await loadPage(kind, locality, null);
      setItems(page.items);
      setCursor(page.next_cursor);
    } catch {
      setError(true);
      setItems([]);
    } finally {
      setLoading(false);
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
            setItems((current) => [...current, ...page.items]);
            setCursor(page.next_cursor);
          })
          .catch(() => undefined)
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
        <EventCard key={item.public_id} item={item} />
      ))}
      {cursor ? <div ref={sentinel} className="h-8" /> : null}
      {loadingMore ? <FeedSkeleton rows={2} /> : null}
    </div>
  );
}
