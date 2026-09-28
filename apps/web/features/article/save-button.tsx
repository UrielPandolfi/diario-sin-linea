"use client";

import { useReaderAuthenticated } from "@/features/auth/reader-context";
import { PublicApiError } from "@/lib/api/public";
import { loginPath } from "@/lib/auth/return-to";
import { publishSaved, subscribeSaved } from "@/lib/saved/sync";
import { Bookmark } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

export function SaveButton({
  slug,
  returnTo,
  guest,
  onChange,
}: {
  slug: string;
  returnTo: string;
  guest?: boolean;
  onChange?: (saved: boolean) => void;
}) {
  const authenticated = useReaderAuthenticated();
  const isGuest = guest ?? !authenticated;
  const [saved, setSaved] = useState<boolean | null>(isGuest ? false : null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    return subscribeSaved((changed, next) => {
      if (changed === slug) setSaved(next);
    });
  }, [slug]);

  useEffect(() => {
    if (isGuest) return;
    let cancelled = false;
    void fetch(`/api/v1/articles/${encodeURIComponent(slug)}/save`, { cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) throw new PublicApiError("request_failed", response.status);
        return (await response.json()) as { saved: boolean };
      })
      .then((payload) => {
        if (!cancelled) setSaved(payload.saved);
      })
      .catch((caught: unknown) => {
        if (cancelled) return;
        if (caught instanceof PublicApiError && caught.status === 401) {
          window.location.assign(loginPath(returnTo));
          return;
        }
        setSaved(false);
      });
    return () => {
      cancelled = true;
    };
  }, [isGuest, returnTo, slug]);

  if (isGuest) {
    return (
      <Link
        href={loginPath(returnTo)}
        aria-label="Iniciar sesión para guardar"
        className="inline-flex items-center gap-1.5 font-sans text-sm text-secondary hover:text-primary"
      >
        <Bookmark className="h-3.5 w-3.5" aria-hidden />
        Guardar
      </Link>
    );
  }

  async function toggle() {
    if (saved === null || pending) return;
    const previous = saved;
    const next = !saved;
    setPending(true);
    setError(null);
    setSaved(next);
    publishSaved(slug, next);
    try {
      const response = await fetch(`/api/v1/articles/${encodeURIComponent(slug)}/save`, {
        method: previous ? "DELETE" : "PUT",
        cache: "no-store",
      });
      if (response.status === 401) {
        setSaved(previous);
        publishSaved(slug, previous);
        window.location.assign(loginPath(returnTo));
        return;
      }
      if (!response.ok) throw new PublicApiError("request_failed", response.status);
      const payload = (await response.json()) as { saved: boolean };
      setSaved(payload.saved);
      publishSaved(slug, payload.saved);
      onChange?.(payload.saved);
    } catch {
      setSaved(previous);
      publishSaved(slug, previous);
      setError(previous ? "No se pudo quitar." : "No se pudo guardar.");
    } finally {
      setPending(false);
    }
  }

  const label = saved ? "Guardado" : "Guardar";

  return (
    <span className="inline-flex flex-col items-start">
      <button
        type="button"
        onClick={() => void toggle()}
        aria-pressed={saved === true}
        aria-label={saved ? "Quitar de guardados" : "Guardar noticia"}
        disabled={saved === null || pending}
        className="inline-flex items-center gap-1.5 font-sans text-sm text-secondary transition-colors hover:text-primary disabled:opacity-60"
      >
        <Bookmark className="h-3.5 w-3.5" aria-hidden fill={saved ? "currentColor" : "none"} />
        {label}
      </button>
      {error ? (
        <span role="alert" className="font-sans text-xs text-secondary">
          {error}
        </span>
      ) : null}
    </span>
  );
}
