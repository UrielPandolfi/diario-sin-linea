"use client";

import { fetchNow } from "@/lib/api/public";
import type { NowItem } from "@/lib/api/types";
import Link from "next/link";
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";

import {
  RadarMasthead,
  RadarScan,
  RadarStamp,
  RadarStatus,
  useRadarArrivals,
  useRadarTravel,
  useTicker,
} from "./radar-chrome";
import { LIVE_POLL_MS } from "./radar";

const RAIL_PREVIEW = 5;

function rowKey(item: NowItem): string {
  return `${item.slug}-${item.occurred_at}`;
}

export function NowPanel({ fill = false }: { fill?: boolean }) {
  const [items, setItems] = useState<NowItem[]>([]);
  const [error, setError] = useState(false);
  const [ready, setReady] = useState(false);
  const [updatedAt, setUpdatedAt] = useState<number | null>(null);
  const now = useTicker();
  const { frameRef, travel } = useRadarTravel(0);
  const listRef = useRef<HTMLOListElement>(null);
  const [clipHeight, setClipHeight] = useState<number | null>(null);
  const visible = fill ? items.slice(0, RAIL_PREVIEW) : items;
  const clip = fill && items.length >= RAIL_PREVIEW;
  const keys = visible.map(rowKey);
  const previewKey = keys.join("\n");
  const { born, nudging } = useRadarArrivals(keys, ready, now);

  useLayoutEffect(() => {
    if (!clip) {
      setClipHeight(null);
      return;
    }
    const list = listRef.current;
    if (!list) return;

    const measure = () => {
      const last = list.lastElementChild;
      if (!(last instanceof HTMLElement)) return;
      const next = Math.round(last.offsetTop + last.offsetHeight / 2);
      setClipHeight((current) => (current === next ? current : next));
    };

    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(list);
    for (const child of list.children) observer.observe(child);
    return () => observer.disconnect();
  }, [clip, previewKey]);

  const load = useCallback(async () => {
    try {
      const payload = await fetchNow(12);
      setItems(payload.items);
      setUpdatedAt(Date.now());
      setReady(true);
      setError(false);
    } catch {
      setError(true);
    }
  }, []);

  useEffect(() => {
    const desktop = window.matchMedia("(min-width: 1024px)");
    let timer = 0;

    const start = () => {
      window.clearInterval(timer);
      timer = 0;
      const active = fill ? desktop.matches : !desktop.matches;
      if (!active) return;
      void load();
      timer = window.setInterval(() => {
        void load();
      }, LIVE_POLL_MS);
    };

    start();
    desktop.addEventListener("change", start);
    return () => {
      desktop.removeEventListener("change", start);
      window.clearInterval(timer);
    };
  }, [fill, load]);

  let body: ReactNode;
  if (error && items.length === 0) {
    body = (
      <div className="py-4 pl-5 pr-4">
        <p className="font-sans text-sm text-secondary">No pudimos actualizar esta lista.</p>
        <button type="button" onClick={() => void load()} className="mt-2 text-sm text-primary underline">
          Reintentar
        </button>
      </div>
    );
  } else if (items.length === 0) {
    body = <p className="py-4 pl-5 pr-4 font-sans text-sm text-secondary">Todavía no hay actualizaciones recientes.</p>;
  } else {
    body = (
      <ol ref={listRef} className="sl-radar-list" data-nudging={nudging ? "true" : undefined}>
        {visible.map((item) => {
          const key = rowKey(item);
          return (
            <li
              key={key}
              data-new={born[key] ? "true" : undefined}
              className="sl-radar-item border-b border-border py-1 pl-5 pr-4 last:border-b-0"
            >
              <Link href={`/noticias/${item.slug}`} className="sl-hit text-primary">
                <RadarStamp
                  iso={item.occurred_at}
                  locality={item.locality}
                  arrivedAt={born[key]}
                  now={now}
                  className="font-sans text-[11px] uppercase tracking-[0.12em] text-muted"
                />
                <p className="mt-1 font-heading text-sm font-semibold leading-snug">{item.headline}</p>
                {item.notice ? <p className="mt-1 font-sans text-xs text-secondary">{item.notice}</p> : null}
              </Link>
            </li>
          );
        })}
      </ol>
    );
  }

  return (
    <section className={fill ? "flex shrink-0 flex-col" : undefined}>
      <header className="z-10 shrink-0 border-b border-border bg-background/90 px-4 py-3 backdrop-blur-md">
        <RadarMasthead now={now} compact as="h2" />
      </header>
      <div
        ref={frameRef}
        className={
          fill
            ? clip
              ? "relative shrink-0 overflow-hidden"
              : "relative"
            : "relative"
        }
        style={clip && clipHeight != null ? { height: clipHeight } : undefined}
      >
        {fill ? (travel > 0 ? <RadarScan travel={travel} /> : null) : <RadarScan flow />}
        {body}
        {clip ? (
          <div
            className="pointer-events-none absolute inset-x-0 bottom-0 z-[3] h-7 bg-gradient-to-b from-transparent to-background"
            aria-hidden
          />
        ) : null}
      </div>
      <RadarStatus now={now} updatedAt={updatedAt} />
    </section>
  );
}
