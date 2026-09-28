"use client";

import { loginPath, registerPath } from "@/lib/auth/return-to";
import { X } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

const DISMISS_KEY = "sl-guest-signup-dismissed";

export function GuestSignupBanner({ returnTo }: { returnTo: string }) {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    try {
      setOpen(sessionStorage.getItem(DISMISS_KEY) !== "1");
    } catch {
      setOpen(true);
    }
  }, []);

  function dismiss() {
    try {
      sessionStorage.setItem(DISMISS_KEY, "1");
    } catch {
      // La invitación igual se oculta en esta vista.
    }
    setOpen(false);
  }

  if (!open) return null;

  return (
    <>
      <div aria-hidden="true" className="h-64 md:h-40" />
      <div className="pointer-events-none fixed inset-x-0 bottom-[calc(4.25rem+env(safe-area-inset-bottom))] z-20 md:bottom-0 md:left-16 lg:left-[15.25rem]">
        <div className="h-16 bg-gradient-to-t from-surface to-transparent" />
        <div className="pointer-events-auto relative border-t border-border bg-surface px-4 pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-3 md:px-8 md:pb-4">
          <div className="mx-auto flex max-w-article flex-col gap-3 pr-8 md:flex-row md:items-center md:justify-between md:pr-10">
            <div className="min-w-0">
              <p className="font-heading text-lg font-medium text-primary">Tu próxima lectura empieza acá.</p>
              <p className="mt-1 font-sans text-sm leading-relaxed text-secondary">
                Creá tu cuenta para acceder al inicio y seguir leyendo Sin Línea.
              </p>
            </div>
            <div className="flex shrink-0 flex-col gap-2 md:flex-row md:items-center">
              <Link
                href={registerPath(returnTo)}
                className="inline-flex min-h-11 w-full items-center justify-center rounded-lg bg-action px-4 font-sans text-sm text-on-action hover:opacity-90 md:w-auto"
              >
                Crear cuenta
              </Link>
              <Link
                href={loginPath(returnTo)}
                className="inline-flex min-h-11 w-full items-center justify-center rounded-lg border border-border bg-surface px-4 font-sans text-sm text-primary hover:bg-hover md:w-auto"
              >
                Ya tengo cuenta
              </Link>
            </div>
          </div>
          <button
            type="button"
            onClick={dismiss}
            aria-label="Cerrar invitación"
            className="absolute right-3 top-3 inline-flex h-11 w-11 items-center justify-center rounded-lg text-muted hover:bg-hover hover:text-primary"
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>
      </div>
    </>
  );
}
