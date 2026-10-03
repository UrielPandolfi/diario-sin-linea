"use client";

import { FeedList } from "@/features/feed/feed-list";
import { LocalitySearch } from "@/features/locality/locality-search";
import { fetchReaderAccount, placeLabel, type ReaderPlace } from "@/lib/auth/account";
import { useEffect, useState } from "react";

export function LocalView() {
  const [place, setPlace] = useState<ReaderPlace | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    void fetchReaderAccount()
      .then((account) => setPlace(account.locality))
      .finally(() => setReady(true));
  }, []);

  if (!ready) {
    return <div className="h-40 animate-pulse bg-surface" />;
  }

  const label = place ? placeLabel(place) : null;

  return (
    <div className="mx-auto min-h-screen max-w-measure">
      <header className="sticky top-0 z-10 space-y-3 border-b border-border bg-background/80 px-4 py-3 backdrop-blur-md md:px-6">
        <div>
          <p className="font-sans text-[12px] uppercase tracking-[0.16em] text-accent">Local</p>
          <h1 className="font-heading text-2xl font-semibold text-primary">{place?.name ?? "Local"}</h1>
          {label ? <p className="mt-1 font-sans text-sm text-secondary">{label}</p> : null}
        </div>
        <LocalitySearch mode="edit" showClear={place !== null} onChanged={setPlace} />
      </header>
      {place ? (
        <FeedList
          key={place.id}
          kind="local"
          locality={place.name}
          province={place.province_name}
          emptyTitle={`No hay sucesos recientes en ${place.name}.`}
          emptyDescription="Cuando ocurra algo relevante aparecerá acá."
        />
      ) : (
        <p className="px-4 py-8 font-sans text-sm text-secondary md:px-5">
          Elegí una localidad para ver los sucesos de ese lugar.
        </p>
      )}
    </div>
  );
}
