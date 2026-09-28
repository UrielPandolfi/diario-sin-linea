"use client";

import { useEffect } from "react";

const DWELL_MS = 10_000;

export function ArticleReadSignal({ slug }: { slug: string }) {
  useEffect(() => {
    let accumulated = 0;
    let visibleSince = document.visibilityState === "visible" ? performance.now() : null;
    let sent = false;

    const flush = () => {
      if (visibleSince === null) return;
      accumulated += performance.now() - visibleSince;
      visibleSince = document.visibilityState === "visible" ? performance.now() : null;
    };

    const send = () => {
      if (sent) return;
      flush();
      if (accumulated < DWELL_MS) return;
      sent = true;
      void fetch(`/api/v1/articles/${encodeURIComponent(slug)}/read`, {
        method: "POST",
        cache: "no-store",
      }).catch(() => undefined);
    };

    const onVisibility = () => {
      if (document.visibilityState === "hidden") {
        flush();
        visibleSince = null;
        return;
      }
      if (visibleSince === null) visibleSince = performance.now();
    };

    const timer = window.setInterval(send, 1000);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [slug]);

  return null;
}
