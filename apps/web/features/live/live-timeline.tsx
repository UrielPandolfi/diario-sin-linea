"use client";

import { FeedEmpty, FeedError, FeedSkeleton } from "@/features/feed/feed-states";
import { fetchLive } from "@/lib/api/public";
import type { EventCard as EventCardType } from "@/lib/api/types";
import { formatClock } from "@/lib/relative-time";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

const POLL_MS = 45_000;

export function LiveTimeline() {
  const [items, setItems] = useState<EventCardType[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState(false);
  const sentinel = useRef<HTMLDivElement>(null);
  const paginated = useRef(false);
  const loadingMoreRef = useRef(false);

  const refresh = useCallback(async (isPoll = false) => {
    if (isPoll && paginated.current) return;
    try {
      const page = await fetchLive();
      setItems(page.items);
      setCursor(page.next_cursor);
      setError(false);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh(false);
    const timer = window.setInterval(() => {
      void refresh(true);
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [refresh]);

  useEffect(() => {
    if (!cursor || loading || error) return;
    const node = sentinel.current;
    if (!node) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (!entries[0]?.isIntersecting || loadingMoreRef.current) return;
        loadingMoreRef.current = true;
        paginated.current = true;
        setLoadingMore(true);
        void fetchLive({ cursor })
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
  }, [cursor, loading, error]);

  if (loading) return <FeedSkeleton />;
  if (error && items.length === 0) return <FeedError onRetry={() => void refresh(false)} />;
  if (items.length === 0) {
    return (
      <FeedEmpty
        title="Nada en vivo por ahora."
        description="Cuando se publique un suceso, va a aparecer acá en orden cronológico."
      />
    );
  }

  return (
    <div>
      {items.map((item) => (
        <Link
          key={item.public_id}
          href={`/noticias/${item.slug}`}
          className="block border-b border-border px-4 py-4 text-primary hover:bg-hover md:px-5"
        >
          <p className="font-sans text-[11px] uppercase tracking-[0.14em] text-muted">
            {formatClock(item.updated_at || item.published_at)}
            {item.locality ? ` · ${item.locality}` : ""}
          </p>
          <p className="mt-1 font-heading text-base leading-snug">{item.headline}</p>
        </Link>
      ))}
      {cursor ? <div ref={sentinel} className="h-8" /> : null}
      {loadingMore ? <FeedSkeleton rows={2} /> : null}
    </div>
  );
}
