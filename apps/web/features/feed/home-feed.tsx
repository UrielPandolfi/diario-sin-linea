"use client";

import { FeedList } from "@/features/feed/feed-list";
import { FeedTabs, parseVista, type HomeVista } from "@/features/feed/feed-tabs";
import { HomeContextBar, HomeRail } from "@/features/shell/home-rail";
import type { FeedScope } from "@/lib/api/types";
import { readLocalityCookie } from "@/lib/locality";
import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

const SCOPE: Record<HomeVista, FeedScope> = {
  "para-vos": "main",
  local: "local",
  argentina: "argentina",
};

function feedKind(vista: HomeVista, locality: string | null): FeedScope {
  if (!locality) return "argentina";
  return SCOPE[vista];
}

export function HomeFeed() {
  const searchParams = useSearchParams();
  const vista = parseVista(searchParams.get("vista"));
  const [locality, setLocality] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    setLocality(readLocalityCookie());
    setReady(true);
  }, []);

  if (!ready) {
    return <div className="h-40 animate-pulse bg-surface" />;
  }

  const kind = feedKind(vista, locality);
  const emptyTitle =
    vista === "local" && locality ? `No hay sucesos recientes en ${locality}.` : "Todavía no hay sucesos publicados.";
  const emptyDescription =
    vista === "local" && locality
      ? "Cuando ocurra algo relevante aparecerá acá."
      : "En cuanto se publique algo, lo vas a ver en este feed.";

  return (
    <div className="flex min-h-screen">
      <div className="min-w-0 flex-1 border-r border-border">
        <HomeContextBar locality={locality} />
        <header className="sticky top-0 z-10 border-b border-border bg-background/95">
          <div className="px-4 py-3 md:px-6">
            <h1 className="font-heading text-2xl font-semibold text-primary">Inicio</h1>
          </div>
          <FeedTabs />
        </header>
        <FeedList
          kind={kind}
          locality={locality ?? undefined}
          emptyTitle={emptyTitle}
          emptyDescription={emptyDescription}
        />
      </div>
      <HomeRail locality={locality} />
    </div>
  );
}
