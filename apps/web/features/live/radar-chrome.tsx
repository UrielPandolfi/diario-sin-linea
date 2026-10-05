"use client";

import { formatClock } from "@/lib/relative-time";
import { useEffect, useRef, useState } from "react";

import { formatLiveClock, formatUpdatedAgo, isFresh, isNewArrival, prefixArrivals, NEW_LABEL_MS } from "./radar";

export function useTicker(): number {
  const [now, setNow] = useState(0);

  useEffect(() => {
    let timer = 0;
    const tick = () => {
      setNow(Date.now());
      timer = window.setTimeout(tick, 1000 - (Date.now() % 1000) + 15);
    };
    tick();
    return () => window.clearTimeout(timer);
  }, []);

  return now;
}

export function useElementHeight<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [height, setHeight] = useState(0);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    const measure = () => setHeight(node.offsetHeight);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  return { ref, height };
}

export function useRadarTravel(stick: number) {
  const frameRef = useRef<HTMLDivElement>(null);
  const [measured, setMeasured] = useState({ stick, travel: 0 });
  if (measured.stick !== stick) {
    setMeasured({ stick, travel: 0 });
  }

  useEffect(() => {
    const node = frameRef.current;
    if (!node) return;

    const apply = (travel: number) => {
      setMeasured((current) => {
        if (current.stick === stick && current.travel === travel) return current;
        return { stick, travel };
      });
    };

    const measure = () => {
      const pane = node.clientHeight;
      if (pane <= 0) {
        apply(0);
        return;
      }
      const cap = Math.max(160, window.innerHeight - stick);
      const scrolling = node.scrollHeight > pane + 8;
      const next = scrolling ? pane : Math.min(node.getBoundingClientRect().height, cap);
      apply(next < 48 ? 0 : Math.round(next));
    };

    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    window.addEventListener("resize", measure);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, [stick]);

  return { frameRef, travel: measured.stick === stick ? measured.travel : 0 };
}

export function useRadarArrivals(keys: readonly string[], ready: boolean, now: number) {
  const previous = useRef<string[] | null>(null);
  const nudgeTimer = useRef(0);
  const signature = keys.join("\n");
  const [born, setBorn] = useState<Record<string, number>>({});
  const [nudging, setNudging] = useState(false);

  useEffect(() => {
    if (!ready) return;
    const list = signature.length > 0 ? signature.split("\n") : [];
    const fresh = prefixArrivals(previous.current, list);
    previous.current = list;
    if (fresh.length === 0) return;
    const stamp = Date.now();
    setBorn((current) => {
      const next = { ...current };
      for (const key of fresh) next[key] = stamp;
      return next;
    });
    setNudging(true);
    window.clearTimeout(nudgeTimer.current);
    nudgeTimer.current = window.setTimeout(() => setNudging(false), 1000);
  }, [ready, signature]);

  useEffect(() => {
    const timer = nudgeTimer;
    return () => window.clearTimeout(timer.current);
  }, []);

  useEffect(() => {
    setBorn((current) => {
      let changed = false;
      const next: Record<string, number> = {};
      for (const [key, stamp] of Object.entries(current)) {
        if (now - stamp < NEW_LABEL_MS) next[key] = stamp;
        else changed = true;
      }
      return changed ? next : current;
    });
  }, [now]);

  return { born, nudging };
}

function ActivityWave() {
  return (
    <span className="sl-radar-wave" aria-hidden>
      <span />
      <span />
      <span />
      <span />
      <span />
    </span>
  );
}

export function RadarMasthead({
  now,
  compact = false,
  as: Tag = "p",
}: {
  now: number;
  compact?: boolean;
  as?: "h2" | "p";
}) {
  return (
    <Tag
      className={`flex flex-wrap items-center gap-x-2 gap-y-1 font-sans font-medium uppercase text-accent ${
        compact ? "text-[11px] tracking-[0.14em]" : "text-[12px] tracking-[0.16em]"
      }`}
    >
      <span className="sl-live-dot shrink-0" aria-hidden />
      <span>Ahora</span>
      <span aria-hidden className="text-muted">
        ·
      </span>
      <span>En vivo</span>
      <span className="ml-auto inline-flex items-center gap-2 normal-case tracking-normal">
        <time className="inline-block min-w-[4.8rem] text-right text-secondary tabular-nums" aria-hidden>
          {now > 0 ? formatLiveClock(now) : ""}
        </time>
        <ActivityWave />
      </span>
    </Tag>
  );
}

function RadarMarks() {
  return (
    <>
      <span className="sl-radar-line" />
      <span className="sl-radar-pulse" />
      <span className="sl-radar-sweep" />
    </>
  );
}

export function RadarScan({
  stick = 0,
  travel = 0,
  flow = false,
}: {
  stick?: number;
  travel?: number;
  flow?: boolean;
}) {
  if (flow) {
    return (
      <div className="sl-radar-flow" aria-hidden>
        <RadarMarks />
      </div>
    );
  }
  if (travel <= 0) return null;
  return (
    <div className="sl-radar-anchor" style={{ top: stick }} aria-hidden>
      <div className="sl-radar-scan" style={{ height: travel }}>
        <RadarMarks />
      </div>
    </div>
  );
}

export function RadarStamp({
  iso,
  locality,
  arrivedAt,
  now,
  className,
}: {
  iso: string | null;
  locality: string | null;
  arrivedAt?: number;
  now: number;
  className: string;
}) {
  const fresh = isNewArrival(arrivedAt, now);
  const recent = !fresh && isFresh(iso, now);
  const place = [formatClock(iso), locality].filter(Boolean).join(" · ");

  return (
    <p className={`flex items-center ${className}`}>
      {fresh ? (
        <span className="sl-radar-new">
          Nuevo
          {place ? <span aria-hidden> · </span> : null}
        </span>
      ) : null}
      {recent ? <span className="sl-radar-fresh mr-1.5" aria-hidden /> : null}
      {place ? <span>{place}</span> : null}
    </p>
  );
}

export function RadarStatus({
  now,
  updatedAt,
  pin = false,
}: {
  now: number;
  updatedAt: number | null;
  pin?: boolean;
}) {
  return (
    <footer
      className={`border-t border-border bg-background/90 px-4 py-2.5 backdrop-blur-md ${
        pin ? "sticky bottom-16 z-10 md:bottom-0" : "shrink-0"
      }`}
    >
      <p className="flex flex-wrap items-center gap-x-2 gap-y-0.5 font-sans text-[11px] text-muted">
        <span className="sl-live-dot" aria-hidden />
        <span className="uppercase tracking-[0.14em] text-secondary">Radar activo</span>
        {updatedAt != null && now > 0 ? (
          <span className="tabular-nums" aria-hidden>
            · {formatUpdatedAgo(updatedAt, now)}
          </span>
        ) : null}
      </p>
    </footer>
  );
}
