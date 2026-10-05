"use client";

import { FeedEmpty, FeedError, FeedSkeleton } from "@/features/feed/feed-states";
import { PublicHero } from "@/features/article/public-hero";
import { PublicApiError, fetchLive } from "@/lib/api/public";
import { loginPath } from "@/lib/auth/return-to";
import type { EventCard as EventCardType } from "@/lib/api/types";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

import {
  RadarMasthead,
  RadarScan,
  RadarStamp,
  RadarStatus,
  useElementHeight,
  useRadarArrivals,
  useRadarTravel,
  useTicker,
} from "./radar-chrome";
import { LIVE_POLL_MS } from "./radar";

export function LiveTimeline() {
  const [items, setItems] = useState<EventCardType[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState(false);
  const [ready, setReady] = useState(false);
  const [updatedAt, setUpdatedAt] = useState<number | null>(null);
  const sentinel = useRef<HTMLDivElement>(null);
  const paginated = useRef(false);
  const loadingMoreRef = useRef(false);

  const refresh = useCallback(async (isPoll = false) => {
    if (isPoll && paginated.current) return;
    try {
      const page = await fetchLive();
      setItems(page.items);
      setCursor(page.next_cursor);
      setUpdatedAt(Date.now());
      setReady(true);
      setError(false);
    } catch (error) {
      if (error instanceof PublicApiError && error.status === 401) {
        window.location.assign(loginPath("/en-vivo"));
        return;
      }
      setError(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh(false);
    const timer = window.setInterval(() => {
      void refresh(true);
    }, LIVE_POLL_MS);
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

  const now = useTicker();
  const { ref: headerRef, height: headerHeight } = useElementHeight<HTMLElement>();
  const { frameRef, travel } = useRadarTravel(headerHeight);
  const keys = items.map((item) => item.public_id);
  const { born, nudging } = useRadarArrivals(keys, ready, now);

  let body: ReactNode;
  if (loading) body = <FeedSkeleton />;
  else if (error && items.length === 0) body = <FeedError onRetry={() => void refresh(false)} />;
  else if (items.length === 0) {
    body = (
      <FeedEmpty
        title="Nada en vivo por ahora."
        description="Cuando se publique un suceso, va a aparecer acá en orden cronológico."
      />
    );
  } else {
    body = (
      <>
        <div className="sl-radar-list" data-nudging={nudging ? "true" : undefined}>
          {items.map((item) => (
            <Link
              key={item.public_id}
              href={`/noticias/${item.slug}`}
              data-new={born[item.public_id] ? "true" : undefined}
              className="sl-feed-item sl-radar-item group block border-b border-border py-5 pl-5 pr-4 text-primary md:pl-6 md:pr-6"
            >
              <RadarStamp
                iso={item.updated_at || item.published_at}
                locality={item.locality}
                arrivedAt={born[item.public_id]}
                now={now}
                className="font-sans text-[12px] uppercase tracking-[0.14em] text-accent"
              />
              <p className="mt-1.5 font-heading text-[1.15rem] font-semibold leading-snug">{item.headline}</p>
              {item.hero_image_url ? (
                <PublicHero
                  src={item.hero_image_url}
                  className="mt-3 overflow-hidden rounded-xl"
                  sizes="(min-width: 768px) 672px, 100vw"
                />
              ) : null}
            </Link>
          ))}
        </div>
        {cursor ? <div ref={sentinel} className="h-8" /> : null}
        {loadingMore ? <FeedSkeleton rows={2} /> : null}
      </>
    );
  }

  return (
    <div>
      <header
        ref={headerRef}
        className="sticky top-0 z-10 border-b border-border bg-background/90 py-3 pl-5 pr-4 backdrop-blur-md md:px-6"
      >
        <RadarMasthead now={now} />
        <h1 className="font-heading text-2xl font-semibold text-primary">En vivo</h1>
      </header>
      <div ref={frameRef} className="relative">
        {travel > 0 && headerHeight > 0 ? <RadarScan stick={headerHeight} travel={travel} /> : null}
        {body}
      </div>
      <RadarStatus now={now} updatedAt={updatedAt} pin />
    </div>
  );
}
