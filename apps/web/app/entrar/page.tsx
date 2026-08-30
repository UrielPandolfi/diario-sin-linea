"use client";

import { BrandMark } from "@/features/shell/brand-mark";
import { Apple, Mail } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

export default function EntrarPage() {
  return (
    <main className="min-h-screen bg-background">
      <div className="mx-auto grid min-h-screen max-w-[1100px] lg:grid-cols-[minmax(0,1.1fr)_minmax(0,0.9fr)]">
        <section className="flex flex-col justify-between px-8 py-10 md:px-14 md:py-16">
          <div className="flex items-center gap-2 text-accent-ochre">
            <BrandMark className="h-9 w-9" />
            <span className="font-heading text-sm font-medium uppercase tracking-[0.18em]">Sin Línea</span>
          </div>
          <div className="max-w-md py-16 lg:py-0">
            <h1 className="font-heading text-4xl font-medium leading-[1.1] tracking-tight text-primary md:text-5xl">
              Entendé qué está pasando.
            </h1>
            <p className="mt-5 max-w-sm font-sans text-base leading-relaxed text-secondary">
              Información basada en hechos, fuentes y evidencia.
            </p>
          </div>
          <p className="hidden font-sans text-xs text-muted lg:block">Medio informativo centrado en sucesos.</p>
        </section>

        <section className="flex flex-col justify-center border-t border-border px-8 py-12 lg:border-l lg:border-t-0 lg:px-14">
          <p className="font-heading text-xs uppercase tracking-[0.16em] text-muted">Bienvenida</p>
          <h2 className="mt-3 font-heading text-2xl font-medium text-primary">Explorá Sin Línea</h2>
          <p className="mt-2 max-w-xs font-sans text-sm text-secondary">
            Elegí tu localidad y mirá qué está ocurriendo ahora.
          </p>
          <Link
            href="/onboarding"
            className="mt-8 inline-flex w-full max-w-sm items-center justify-center border border-border bg-hover px-4 py-3 font-sans text-sm text-primary transition-colors hover:bg-surface-secondary"
          >
            Explorar Sin Línea
          </Link>

          <div className="mt-10 max-w-sm">
            <div className="flex items-center gap-3 text-[11px] uppercase tracking-[0.16em] text-muted">
              <span className="h-px flex-1 bg-border" />
              Crear una cuenta
              <span className="h-px flex-1 bg-border" />
            </div>
            <p className="mt-3 font-sans text-xs text-muted">Próximamente</p>
            <div className="mt-4 space-y-2">
              <DisabledAccountButton icon={<GoogleMark />}>Continuar con Google</DisabledAccountButton>
              <DisabledAccountButton icon={<Apple className="h-4 w-4" aria-hidden />}>
                Continuar con Apple
              </DisabledAccountButton>
              <DisabledAccountButton icon={<Mail className="h-4 w-4" aria-hidden />}>
                Continuar con email
              </DisabledAccountButton>
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}

function GoogleMark() {
  return (
    <svg viewBox="0 0 24 24" className="h-4 w-4" aria-hidden="true">
      <path
        fill="currentColor"
        d="M21.6 12.23c0-.74-.06-1.28-.2-1.84H12v3.34h5.5c-.11.9-.72 2.26-2.08 3.18v2.64h3.36c1.97-1.81 3.12-4.48 3.12-7.32Z"
      />
      <path
        fill="currentColor"
        d="M12 22c2.8 0 5.15-.92 6.86-2.45l-3.36-2.64c-.9.62-2.1 1.06-3.5 1.06-2.68 0-4.96-1.79-5.77-4.21H2.76v2.72C4.46 19.98 8 22 12 22Z"
      />
      <path
        fill="currentColor"
        d="M6.23 13.76c-.2-.62-.32-1.28-.32-1.76s.11-1.14.32-1.76V7.52H2.76A9.96 9.96 0 0 0 2 12c0 1.61.38 3.13 1.04 4.48l3.19-2.72Z"
      />
      <path
        fill="currentColor"
        d="M12 5.98c1.54 0 2.9.53 3.98 1.57l2.96-2.96C16.94 2.89 14.79 2 12 2 8 2 4.46 4.02 2.76 7.52l3.47 2.72C7.04 7.82 9.32 5.98 12 5.98Z"
      />
    </svg>
  );
}

function DisabledAccountButton({ children, icon }: { children: string; icon?: ReactNode }) {
  return (
    <button
      type="button"
      disabled
      className="flex w-full items-center justify-center gap-2 border border-border bg-surface px-4 py-2.5 font-sans text-sm text-muted"
    >
      {icon}
      {children}
    </button>
  );
}
