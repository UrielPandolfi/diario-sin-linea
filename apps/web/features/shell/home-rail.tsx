"use client";

import { NearbyPanel } from "@/features/nearby/nearby-panel";
import { NowPanel } from "@/features/live/now-panel";
import { ContextSheets } from "@/features/shell/context-sheets";

function NearbyPrompt() {
  return (
    <p className="px-4 py-4 font-sans text-sm text-secondary">Elegí una localidad para ver qué hay cerca.</p>
  );
}

function NearbyBody({ label, divided }: { label: string | null; divided: boolean }) {
  if (!label) return <NearbyPrompt />;
  return <NearbyPanel label={label} divided={divided} />;
}

function NearbySlot({
  label,
  divided,
  pending,
}: {
  label: string | null;
  divided: boolean;
  pending: boolean;
}) {
  if (pending && !label) return <div className="mx-4 my-4 h-16 animate-pulse bg-surface" />;
  return <NearbyBody label={label} divided={divided} />;
}

export function SectionContextBar({
  label,
  now = false,
  nearby = false,
  pending = false,
}: {
  label: string | null;
  now?: boolean;
  nearby?: boolean;
  pending?: boolean;
}) {
  if (!now && !nearby) return null;
  return (
    <div className="lg:hidden">
      <ContextSheets
        now={now ? <NowPanel /> : undefined}
        nearby={nearby ? <NearbySlot label={label} divided pending={pending} /> : undefined}
      />
    </div>
  );
}

export function SectionRail({
  label,
  now = false,
  nearby = false,
  pending = false,
}: {
  label: string | null;
  now?: boolean;
  nearby?: boolean;
  pending?: boolean;
}) {
  if (!now && !nearby) return null;
  const showNearby = nearby && (pending || !now || label !== null);
  return (
    <aside className="hidden w-[18rem] shrink-0 flex-col border-border lg:sticky lg:top-0 lg:flex lg:h-dvh lg:border-r">
      {now ? <NowPanel fill /> : null}
      {showNearby ? (
        <div
          className={
            now
              ? "max-h-[40%] shrink-0 overflow-y-auto"
              : "min-h-0 flex-1 overflow-y-auto"
          }
        >
          <NearbySlot label={label} divided={now} pending={pending} />
        </div>
      ) : null}
    </aside>
  );
}

export function HomeContextBar({ label }: { label: string | null }) {
  return <SectionContextBar label={label} now nearby />;
}

export function HomeRail({ label }: { label: string | null }) {
  return <SectionRail label={label} now nearby />;
}
