"use client";

import { FeedList } from "@/features/feed/feed-list";
import { FeedTabs, parseVista } from "@/features/feed/feed-tabs";
import { LocalitySearch } from "@/features/locality/locality-search";
import { HomeContextBar, HomeRail } from "@/features/shell/home-rail";
import { fetchReaderAccount, placeLabel, type ReaderPlace } from "@/lib/auth/account";
import { MapPin } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

export function HomeFeed() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const vista = parseVista(searchParams.get("vista"));
  const [place, setPlace] = useState<ReaderPlace | null>(null);
  const [ready, setReady] = useState(false);
  const [editing, setEditing] = useState(false);
  const query = searchParams.toString();

  useEffect(() => {
    let cancelled = false;
    void fetchReaderAccount().then((account) => {
      if (cancelled) return;
      if (account.locality_step === "pending") {
        const next = query ? `${pathname}?${query}` : pathname;
        router.replace(`/onboarding?next=${encodeURIComponent(next)}`);
        return;
      }
      setPlace(account.locality);
      setReady(true);
    });
    return () => {
      cancelled = true;
    };
  }, [pathname, query, router]);

  if (!ready) {
    return <div className="h-40 animate-pulse bg-surface" />;
  }

  const sort = vista === "ultimas" ? "latest" : "principal";
  const label = place ? placeLabel(place) : null;

  return (
    <div className="flex min-h-screen">
      <div className="min-w-0 flex-1 border-r border-border">
        <HomeContextBar label={label} />
        <header className="sticky top-0 z-10 border-b border-border bg-background/80 backdrop-blur-md">
          <div className="px-4 py-3 md:px-6">
            <h1 className="font-heading text-2xl font-semibold text-primary">Inicio</h1>
            {label ? (
              <button type="button" className="sl-chip mt-2" onClick={() => setEditing((open) => !open)}>
                <MapPin className="h-3.5 w-3.5 text-accent" aria-hidden />
                {label}
              </button>
            ) : (
              <button type="button" className="sl-chip mt-2" onClick={() => setEditing(true)}>
                <MapPin className="h-3.5 w-3.5 text-accent-ochre" aria-hidden />
                Elegí una localidad
              </button>
            )}
            {editing ? (
              <div className="mt-3 max-w-md">
                <LocalitySearch
                  mode="edit"
                  showClear={place !== null}
                  onChanged={(next) => {
                    setPlace(next);
                    setEditing(false);
                  }}
                />
              </div>
            ) : null}
          </div>
          <FeedTabs />
        </header>
        <FeedList
          key={`${sort}:${place?.id ?? ""}`}
          kind={sort}
          emptyTitle="Todavía no hay sucesos publicados."
          emptyDescription="En cuanto se publique algo, lo vas a ver en este feed."
        />
      </div>
      <HomeRail label={label} />
    </div>
  );
}
