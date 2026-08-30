"use client";

import { UpcomingFeature } from "@/features/upcoming/upcoming-feature";
import { NearbyPanel } from "@/features/nearby/nearby-panel";
import { NowPanel } from "@/features/live/now-panel";
import { ContextSheets } from "@/features/shell/context-sheets";

export function HomeContextBar({ locality }: { locality: string }) {
  return (
    <div className="lg:hidden">
      <ContextSheets now={<NowPanel />} nearby={<NearbyPanel locality={locality} />} />
    </div>
  );
}

export function HomeRail({ locality }: { locality: string }) {
  return (
    <aside className="hidden min-h-screen w-[280px] shrink-0 overflow-y-auto lg:sticky lg:top-0 lg:block lg:h-screen lg:border-l lg:border-border">
      <NowPanel />
      <NearbyPanel locality={locality} />
      <div className="border-t border-border">
        <UpcomingFeature compact title="Mapa" description="Explorá qué está pasando alrededor tuyo." />
      </div>
    </aside>
  );
}
