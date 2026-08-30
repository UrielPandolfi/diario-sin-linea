"use client";

import type { ReactNode } from "react";

export function UpcomingFeature({
  title,
  description,
  compact = false,
}: {
  title: string;
  description: string;
  compact?: boolean;
}) {
  return (
    <section className={`relative overflow-hidden ${compact ? "min-h-[220px]" : "min-h-[420px]"}`}>
      <div className="pointer-events-none select-none opacity-40 blur-[2px]" aria-hidden="true">
        <UpcomingPreview />
      </div>
      <div className="absolute inset-0 flex flex-col items-center justify-center bg-background/55 px-6 text-center">
        <p className="font-heading text-xs font-medium uppercase tracking-[0.18em] text-accent-ochre">
          Próximamente
        </p>
        {compact ? (
          <p className="mt-3 font-heading text-xl font-medium text-primary">{title}</p>
        ) : (
          <h1 className="mt-3 font-heading text-2xl font-medium text-primary">{title}</h1>
        )}
        <p className="mt-2 max-w-sm font-sans text-sm text-secondary">{description}</p>
      </div>
    </section>
  );
}

function UpcomingPreview() {
  return (
    <div className="space-y-0 px-5 py-6">
      {Array.from({ length: 7 }, (_, index) => (
        <div key={index} className="space-y-2 border-b border-border py-4">
          <div className="h-2 w-20 bg-surface-secondary" />
          <div className="h-3 w-full bg-surface-secondary" />
          <div className="h-3 w-2/3 bg-surface-secondary" />
        </div>
      ))}
    </div>
  );
}

export function UpcomingAction({ children }: { children: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5 font-sans text-sm text-muted">
      {children}
      <span className="text-[10px] uppercase tracking-[0.14em] text-accent-ochre">Próximamente</span>
    </span>
  );
}
