"use client";

import {
  clearReaderLocality,
  placeLabel,
  saveReaderLocality,
  searchLocalities,
  skipReaderLocality,
  type ReaderPlace,
} from "@/lib/auth/account";
import { FormEvent, useEffect, useId, useState } from "react";

const WAIT_MS = 300;

export function LocalitySearch({
  mode,
  showClear = false,
  onChanged,
  onFinished,
}: {
  mode: "prompt" | "edit";
  showClear?: boolean;
  onChanged?: (place: ReaderPlace | null) => void;
  onFinished?: () => void;
}) {
  const listId = useId();
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<ReaderPlace[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [chosen, setChosen] = useState<ReaderPlace | null>(null);
  const [status, setStatus] = useState<"idle" | "loading" | "empty" | "error">("idle");
  const [retry, setRetry] = useState(0);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    if (chosen && query === placeLabel(chosen)) {
      setItems([]);
      setStatus("idle");
      setOpen(false);
      return;
    }
    const folded = query.trim();
    if (folded.length < 2) {
      setItems([]);
      setStatus("idle");
      setOpen(false);
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setStatus("loading");
      setOpen(true);
      void searchLocalities(folded, controller.signal)
        .then((next) => {
          setItems(next);
          setActive(0);
          setStatus(next.length === 0 ? "empty" : "idle");
        })
        .catch((error: unknown) => {
          if (error instanceof DOMException && error.name === "AbortError") return;
          setItems([]);
          setStatus("error");
        });
    }, WAIT_MS);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [chosen, query, retry]);

  function pick(place: ReaderPlace) {
    setChosen(place);
    setQuery(placeLabel(place));
    setOpen(false);
    setSaveError(null);
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!chosen) return;
    setSaving(true);
    setSaveError(null);
    try {
      const saved = await saveReaderLocality(chosen.id);
      onChanged?.(saved);
      onFinished?.();
    } catch (error) {
      setSaveError(error instanceof Error && error.message === "missing"
        ? "Esa localidad no está en el catálogo."
        : mode === "prompt"
          ? "No se pudo guardar. Podés reintentar u omitir el paso."
          : "No se pudo guardar.");
    } finally {
      setSaving(false);
    }
  }

  async function onSkip() {
    setSaving(true);
    setSaveError(null);
    try {
      await skipReaderLocality();
      onChanged?.(null);
      onFinished?.();
    } catch {
      setSaveError("No se pudo omitir el paso. La cuenta sigue activa: reintentá.");
    } finally {
      setSaving(false);
    }
  }

  async function onClear() {
    setSaving(true);
    setSaveError(null);
    try {
      await clearReaderLocality();
      setChosen(null);
      setQuery("");
      onChanged?.(null);
    } catch {
      setSaveError("No se pudo quitar la localidad.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="space-y-3">
      <div className="relative">
        <label className="block font-sans text-sm text-secondary" htmlFor={`${listId}-input`}>
          Localidad
          <input
            id={`${listId}-input`}
            role="combobox"
            aria-expanded={open}
            aria-controls={listId}
            aria-autocomplete="list"
            aria-activedescendant={open && items[active] ? `${listId}-${items[active].id}` : undefined}
            value={query}
            autoComplete="off"
            placeholder="Buscar localidad"
            onChange={(event) => {
              setQuery(event.target.value);
              setChosen(null);
              setSaveError(null);
            }}
            onFocus={() => {
              if (items.length > 0 || status !== "idle") setOpen(true);
            }}
            onKeyDown={(event) => {
              if (!items.length && (event.key === "ArrowDown" || event.key === "ArrowUp")) return;
              if (event.key === "ArrowDown") {
                event.preventDefault();
                setOpen(true);
                setActive((index) => Math.min(items.length - 1, index + 1));
              } else if (event.key === "ArrowUp") {
                event.preventDefault();
                setActive((index) => Math.max(0, index - 1));
              } else if (event.key === "Escape") {
                setOpen(false);
              } else if (event.key === "Enter" && open && items[active]) {
                event.preventDefault();
                pick(items[active]);
              }
            }}
            className="sl-input mt-1"
          />
        </label>
        {open ? (
          <div className="absolute z-20 mt-1 max-h-64 w-full overflow-auto border border-border bg-background">
            {status === "loading" ? <p className="px-3 py-2 font-sans text-sm text-secondary">Buscando…</p> : null}
            {status === "empty" ? (
              <p className="px-3 py-2 font-sans text-sm text-secondary">
                No encontramos esa localidad.{mode === "prompt" ? " Podés omitir el paso." : ""}
              </p>
            ) : null}
            {status === "error" ? (
              <p className="px-3 py-2 font-sans text-sm text-secondary">
                No se pudo buscar.{" "}
                <button type="button" className="underline" onClick={() => setRetry((value) => value + 1)}>
                  Reintentar
                </button>
              </p>
            ) : null}
            {items.length > 0 ? (
              <ul id={listId} role="listbox" aria-label="Localidades">
                {items.map((item, index) => (
                  <li key={item.id} role="presentation">
                    <button
                      id={`${listId}-${item.id}`}
                      type="button"
                      role="option"
                      aria-selected={index === active || chosen?.id === item.id}
                      onMouseEnter={() => setActive(index)}
                      onClick={() => pick(item)}
                      className={`block w-full px-3 py-2 text-left font-sans text-sm text-primary ${
                        index === active ? "bg-hover" : "bg-background"
                      }`}
                    >
                      {placeLabel(item)}
                    </button>
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        ) : null}
      </div>
      {saveError ? (
        <p role="alert" className="font-sans text-sm text-accent-ochre">
          {saveError}
        </p>
      ) : null}
      <button type="submit" className="sl-btn-primary" disabled={saving || chosen === null}>
        {saving ? "Guardando…" : mode === "prompt" ? "Continuar" : "Guardar"}
      </button>
      {mode === "prompt" ? (
        <button type="button" className="sl-btn w-full" disabled={saving} onClick={() => void onSkip()}>
          Ahora no
        </button>
      ) : null}
      {mode === "edit" && showClear ? (
        <button type="button" className="sl-btn" disabled={saving} onClick={() => void onClear()}>
          Quitar
        </button>
      ) : null}
    </form>
  );
}
