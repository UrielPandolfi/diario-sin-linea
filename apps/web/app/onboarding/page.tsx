"use client";

import { BrandMark } from "@/features/shell/brand-mark";
import { fetchLocalities } from "@/lib/api/public";
import { readLocalityCookie, writeLocalityCookie } from "@/lib/locality";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";

export default function OnboardingPage() {
  const router = useRouter();
  const [options, setOptions] = useState<string[]>([]);
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loadingList, setLoadingList] = useState(true);

  useEffect(() => {
    const existing = readLocalityCookie();
    if (existing) setValue(existing);
    void fetchLocalities()
      .then((payload) => {
        setOptions(payload.items);
        if (!existing && payload.items.includes("Rosario")) setValue("Rosario");
        else if (!existing && payload.items[0]) setValue(payload.items[0]);
      })
      .catch(() => setOptions([]))
      .finally(() => setLoadingList(false));
  }, []);

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    const locality = value.trim();
    if (!locality) {
      setError("Elegí una localidad para continuar.");
      return;
    }
    writeLocalityCookie(locality);
    router.push("/");
    router.refresh();
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-6">
      <div className="flex items-center gap-2 text-accent-ochre">
        <BrandMark className="h-8 w-8" />
        <span className="font-heading text-sm font-medium uppercase tracking-[0.18em]">Sin Línea</span>
      </div>
      <p className="mt-10 font-heading text-xs uppercase tracking-[0.16em] text-muted">Paso 1</p>
      <h1 className="mt-2 font-heading text-3xl font-medium text-primary">Tu localidad</h1>
      <p className="mt-2 font-sans text-sm text-secondary">¿Dónde querés recibir información local?</p>

      <form onSubmit={onSubmit} className="mt-8 space-y-4">
        <label className="block font-sans text-sm text-secondary">
          Localidad
          {loadingList ? (
            <div className="mt-1 h-10 w-full animate-pulse bg-surface-secondary" />
          ) : options.length > 0 ? (
            <select
              value={value}
              onChange={(event) => {
                setValue(event.target.value);
                setError(null);
              }}
              className="mt-1 w-full border border-border bg-background px-3 py-2 font-sans text-primary"
            >
              <option value="">Elegí una localidad</option>
              {options.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          ) : (
            <input
              value={value}
              onChange={(event) => {
                setValue(event.target.value);
                setError(null);
              }}
              placeholder="Rosario"
              className="mt-1 w-full border border-border bg-background px-3 py-2 font-sans text-primary"
            />
          )}
        </label>
        {error ? <p className="font-sans text-sm text-accent-ochre">{error}</p> : null}
        <button
          type="submit"
          className="w-full border border-border bg-hover px-3 py-2.5 font-sans text-sm text-primary hover:bg-surface-secondary"
        >
          Continuar
        </button>
      </form>
    </main>
  );
}
