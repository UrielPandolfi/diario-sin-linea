"use client";

import { formatRelative } from "@/lib/relative-time";
import { useEffect, useState } from "react";

export function RelativeTime({ iso, prefix }: { iso: string | null; prefix?: string }) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 30_000);
    return () => window.clearInterval(timer);
  }, []);

  const label = formatRelative(iso, now);
  if (!label) return null;
  return (
    <time dateTime={iso ?? undefined}>
      {prefix}
      {label}
    </time>
  );
}
