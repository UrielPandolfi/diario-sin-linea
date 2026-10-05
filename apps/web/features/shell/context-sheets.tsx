"use client";

import { Clock, MapPin, X } from "lucide-react";
import { useEffect, useId, useState, type ReactNode } from "react";

export function ContextSheets({
  now,
  nearby,
}: {
  now?: ReactNode;
  nearby?: ReactNode;
}) {
  const [open, setOpen] = useState<"now" | "nearby" | null>(null);
  const titleId = useId();
  const sheet = open === "now" ? now : open === "nearby" ? nearby : null;

  useEffect(() => {
    if (!open) return;
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(null);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  if (!now && !nearby) return null;

  return (
    <>
      <div className="sticky top-0 z-20 flex border-b border-border bg-background lg:hidden">
        {now ? (
          <button
            type="button"
            onClick={() => setOpen("now")}
            className="flex flex-1 items-center justify-center gap-2 py-2.5 font-sans text-xs text-secondary hover:bg-hover hover:text-primary"
          >
            <Clock className="h-3.5 w-3.5" aria-hidden />
            Ahora
          </button>
        ) : null}
        {nearby ? (
          <button
            type="button"
            onClick={() => setOpen("nearby")}
            className={`flex flex-1 items-center justify-center gap-2 py-2.5 font-sans text-xs text-secondary hover:bg-hover hover:text-primary ${now ? "border-l border-border" : ""}`}
          >
            <MapPin className="h-3.5 w-3.5" aria-hidden />
            Cerca tuyo
          </button>
        ) : null}
      </div>

      {sheet ? (
        <div className="fixed inset-0 z-40 lg:hidden">
          <button
            type="button"
            aria-label="Cerrar"
            className="absolute inset-0 bg-background/70"
            onClick={() => setOpen(null)}
          />
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby={titleId}
            className="absolute inset-x-0 bottom-0 max-h-[80vh] overflow-y-auto rounded-t-2xl border-t border-border bg-surface pb-16"
          >
            <div className="flex items-center justify-between border-b border-border px-4 py-3">
              <h2 id={titleId} className="font-heading text-base text-primary">
                {open === "now" ? "Ahora" : "Cerca tuyo"}
              </h2>
              <button
                type="button"
                onClick={() => setOpen(null)}
                className="p-1 text-secondary hover:text-primary"
                aria-label="Cerrar panel"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            {sheet}
          </div>
        </div>
      ) : null}
    </>
  );
}
