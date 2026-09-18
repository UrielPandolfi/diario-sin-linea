"use client";

import { useCallback, useEffect, useState } from "react";
import { adminJson, type AdminIngestionSettings } from "@/lib/admin";

export function AutoPollToggle() {
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const ingestion = await adminJson<AdminIngestionSettings>("/api/v1/admin/ingestion");
    setEnabled(ingestion.auto_poll_enabled);
  }, []);

  useEffect(() => {
    void load().catch(() => {
      setError("No se pudo leer el procesamiento automático.");
    });
  }, [load]);

  async function toggle() {
    if (enabled == null || busy) return;
    setBusy(true);
    setError(null);
    try {
      const next = await adminJson<AdminIngestionSettings>("/api/v1/admin/ingestion", {
        method: "PATCH",
        body: JSON.stringify({ auto_poll_enabled: !enabled }),
      });
      setEnabled(next.auto_poll_enabled);
    } catch (err: unknown) {
      setError(
        err instanceof Error ? err.message : "No se pudo cambiar el procesamiento automático.",
      );
    } finally {
      setBusy(false);
    }
  }

  const paused = enabled === false;
  const status = enabled == null ? "…" : paused ? "Pausado" : "Activo";

  return (
    <div
      className={`border-t border-border ${paused ? "bg-hover" : "bg-background"}`}
    >
      <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-3 px-6 py-3">
        <div>
          <p className="font-heading text-sm font-medium text-primary">
            Procesamiento automático
          </p>
          <p className="mt-0.5 font-sans text-xs text-secondary">
            Beat consulta las fuentes vigiladas cada 5 min. Pausar no apaga el worker: deja de
            encolar polls automáticos. El poll manual sigue disponible.
          </p>
          {error ? <p className="mt-1 font-sans text-xs text-accent-ochre">{error}</p> : null}
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={enabled === true}
          aria-label="Procesamiento automático de fuentes vigiladas"
          disabled={busy || enabled == null}
          onClick={() => void toggle()}
          className="flex items-center gap-3 border border-border bg-surface px-3 py-2 font-sans text-sm text-primary disabled:opacity-60"
        >
          <span
            className={`relative inline-flex h-5 w-9 shrink-0 rounded-full ${
              paused || enabled == null ? "bg-border" : "bg-accent-petrol"
            }`}
          >
            <span
              className={`absolute top-0.5 h-4 w-4 rounded-full bg-background transition-[left,right] ${
                paused || enabled == null ? "left-0.5" : "right-0.5"
              }`}
            />
          </span>
          <span className={paused ? "text-accent-ochre" : "text-primary"}>
            {busy ? "Guardando…" : status}
          </span>
        </button>
      </div>
    </div>
  );
}
