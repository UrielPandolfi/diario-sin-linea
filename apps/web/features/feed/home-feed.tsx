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

export function HomeFeed() {
  const searchParams = useSearchParams();
  const vista = parseVista(searchParams.get("vista"));
  const [locality, setLocality] = useState<string | null>(null);

  useEffect(() => {
    setLocality(readLocalityCookie());
  }, []);

  if (!locality) {
    return <div className="h-40 animate-pulse bg-surface" />;
  }

  const emptyTitle =
    vista === "local" ? `No hay sucesos recientes en ${locality}.` : "Todavía no hay sucesos publicados.";
  const emptyDescription =
    vista === "local"
      ? "Cuando ocurra algo relevante aparecerá acá."
      : "En cuanto se publique algo, lo vas a ver en este feed.";

  return (
    <div className="flex min-h-screen">
      <div className="min-w-0 flex-1 border-r border-border">
        <HomeContextBar locality={locality} />
        <header className="sticky top-0 z-10 border-b border-border bg-background">
          <div className="px-4 py-3 md:px-5">
            <h1 className="font-heading text-lg text-primary">Inicio</h1>
          </div>
          <FeedTabs />
        </header>
        <FeedList
          kind={SCOPE[vista]}
          locality={locality}
          emptyTitle={emptyTitle}
          emptyDescription={emptyDescription}
        />
      </div>
      <HomeRail locality={locality} />
    </div>
  );
}
