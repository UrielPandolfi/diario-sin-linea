"use client";

import { Clock, MapPin, X } from "lucide-react";
import { useEffect, useId, useState, type ReactNode } from "react";

export function ContextSheets({
  now,
  nearby,
}: {
  now: ReactNode;
  nearby: ReactNode;
}) {
  const [open, setOpen] = useState<"now" | "nearby" | null>(null);
  const titleId = useId();

  useEffect(() => {
    if (!open) return;
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(null);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <>
      <div className="sticky top-0 z-20 flex border-b border-border bg-background lg:hidden">
        <button
          type="button"
          onClick={() => setOpen("now")}
          className="flex flex-1 items-center justify-center gap-2 py-2.5 font-sans text-xs text-secondary hover:bg-hover hover:text-primary"
        >
          <Clock className="h-3.5 w-3.5" aria-hidden />
          Ahora
        </button>
        <button
          type="button"
          onClick={() => setOpen("nearby")}
          className="flex flex-1 items-center justify-center gap-2 border-l border-border py-2.5 font-sans text-xs text-secondary hover:bg-hover hover:text-primary"
        >
          <MapPin className="h-3.5 w-3.5" aria-hidden />
          Cerca tuyo
        </button>
      </div>

      {open ? (
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
            className="absolute inset-x-0 bottom-0 max-h-[80vh] overflow-y-auto border-t border-border bg-background pb-16"
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
            {open === "now" ? now : nearby}
          </div>
        </div>
      ) : null}
    </>
  );
}
