"use client";

import { FeedList } from "@/features/feed/feed-list";
import { LocalitySelector } from "@/features/locality/locality-selector";
import { UpcomingFeature } from "@/features/upcoming/upcoming-feature";
import { readLocalityCookie } from "@/lib/locality";
import { useEffect, useState } from "react";

export function LocalView() {
  const [locality, setLocality] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    setLocality(readLocalityCookie());
    setReady(true);
  }, []);

  if (!ready) {
    return <div className="h-40 animate-pulse bg-surface" />;
  }

  return (
    <div className="mx-auto min-h-screen max-w-measure">
      <header className="sticky top-0 z-10 space-y-3 border-b border-border bg-background/95 px-4 py-3 md:px-6">
        <div>
          <p className="font-sans text-[12px] uppercase tracking-[0.16em] text-muted">Local</p>
          <h1 className="font-heading text-2xl font-semibold text-primary">{locality ?? "Local"}</h1>
        </div>
        <LocalitySelector current={locality ?? ""} onSaved={setLocality} />
      </header>
      {locality ? (
        <FeedList
          kind="local"
          locality={locality}
          emptyTitle={`No hay sucesos recientes en ${locality}.`}
          emptyDescription="Cuando ocurra algo relevante aparecerá acá."
        />
      ) : (
        <p className="px-4 py-8 font-sans text-sm text-secondary md:px-5">
          Elegí una localidad para ver los sucesos de ese lugar.
        </p>
      )}
      <UpcomingFeature compact title="Mapa" description="Explorá qué está pasando alrededor tuyo." />
    </div>
  );
}
