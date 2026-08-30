"use client";

import { FeedList } from "@/features/feed/feed-list";
import { LocalitySelector } from "@/features/locality/locality-selector";
import { UpcomingFeature } from "@/features/upcoming/upcoming-feature";
import { readLocalityCookie } from "@/lib/locality";
import { useEffect, useState } from "react";

export function LocalView() {
  const [locality, setLocality] = useState<string | null>(null);

  useEffect(() => {
    setLocality(readLocalityCookie());
  }, []);

  if (!locality) {
    return <div className="h-40 animate-pulse bg-surface" />;
  }

  return (
    <div className="mx-auto min-h-screen max-w-2xl border-x border-border">
      <header className="sticky top-0 z-10 space-y-3 border-b border-border bg-background px-4 py-3 md:px-5">
        <div>
          <p className="font-heading text-xs uppercase tracking-[0.16em] text-accent-ochre">Local</p>
          <h1 className="font-heading text-lg text-primary">{locality}</h1>
        </div>
        <LocalitySelector current={locality} onSaved={setLocality} />
      </header>
      <FeedList
        kind="local"
        locality={locality}
        emptyTitle={`No hay sucesos recientes en ${locality}.`}
        emptyDescription="Cuando ocurra algo relevante aparecerá acá."
      />
      <UpcomingFeature compact title="Mapa" description="Explorá qué está pasando alrededor tuyo." />
    </div>
  );
}
