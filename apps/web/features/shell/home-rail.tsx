"use client";

import { NearbyPanel } from "@/features/nearby/nearby-panel";
import { NowPanel } from "@/features/live/now-panel";
import { ContextSheets } from "@/features/shell/context-sheets";

export function HomeContextBar({ label }: { label: string | null }) {
  return (
    <div className="lg:hidden">
      <ContextSheets
        now={<NowPanel />}
        nearby={
          label ? (
            <NearbyPanel label={label} />
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

export function HomeRail({ label }: { label: string | null }) {
  return (
    <aside className="hidden w-[18rem] shrink-0 flex-col overflow-hidden lg:sticky lg:top-0 lg:flex lg:h-[calc(100dvh-3.75rem)] lg:border-l lg:border-border">
      <NowPanel fill />
      {label ? (
        <div className="max-h-[40%] shrink-0 overflow-y-auto">
          <NearbyPanel label={label} />
        </div>
      ) : null}
    </aside>
  );
}
