"use client";

import { UpcomingFeature } from "@/features/upcoming/upcoming-feature";
import { NearbyPanel } from "@/features/nearby/nearby-panel";
import { NowPanel } from "@/features/live/now-panel";
import { ContextSheets } from "@/features/shell/context-sheets";

export function HomeContextBar({ locality }: { locality: string | null }) {
  return (
    <div className="lg:hidden">
      <ContextSheets
        now={<NowPanel />}
        nearby={
          locality ? (
            <NearbyPanel locality={locality} />
          ) : (
            <p className="px-4 py-4 font-sans text-sm text-secondary">
              Elegí una localidad para ver qué hay cerca.
            </p>
          )
        }
      />
    </div>
  );
}

export function HomeRail({ locality }: { locality: string | null }) {
  return (
    <aside className="hidden min-h-screen w-[18rem] shrink-0 overflow-y-auto lg:sticky lg:top-0 lg:block lg:h-screen lg:border-l lg:border-border">
      <NowPanel />
      {locality ? <NearbyPanel locality={locality} /> : null}
      <div className="border-t border-border">
        <UpcomingFeature compact title="Mapa" description="Explorá qué está pasando alrededor tuyo." />
      </div>
    </aside>
  );
}
