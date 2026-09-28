"use client";

import { SignOutButton } from "@/features/auth/sign-out-button";
import { LocalitySelector } from "@/features/locality/locality-selector";
import { ThemeToggle } from "@/components/theme-toggle";
import { readLocalityCookie } from "@/lib/locality";
import Link from "next/link";
import { useEffect, useState } from "react";

export function ProfileView() {
  const [locality, setLocality] = useState<string | null>(null);
  const [email, setEmail] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    setLocality(readLocalityCookie());
    setReady(true);
    void fetch("/api/v1/auth/session", { credentials: "include", cache: "no-store" })
      .then((response) => (response.ok ? response.json() : null))
      .then((body: { authenticated?: boolean; email?: string } | null) => {
        if (body?.authenticated && typeof body.email === "string") setEmail(body.email);
      })
      .catch(() => undefined);
  }, []);

  if (!ready) {
    return <div className="h-40 animate-pulse bg-surface" />;
  }

  return (
    <div className="mx-auto min-h-screen max-w-measure px-4 py-8 md:px-6">
      <p className="font-sans text-[12px] uppercase tracking-[0.16em] text-muted">Perfil</p>
      <h1 className="mt-2 font-heading text-3xl font-semibold text-primary">Tu espacio</h1>
      <p className="mt-2 font-sans text-sm text-secondary">
        {email ? email : "La sesión abre el inicio. La localidad queda en este dispositivo."}
      </p>

      <section className="mt-8 space-y-2 border-t border-border pt-6">
        <h2 className="font-heading text-sm text-primary">Localidad</h2>
        <LocalitySelector current={locality ?? ""} onSaved={setLocality} />
      </section>

      <section className="mt-8 space-y-3 border-t border-border pt-6">
        <h2 className="font-heading text-sm text-primary">Apariencia</h2>
        <ThemeToggle variant="labeled" />
      </section>

      <section className="mt-8 space-y-2 border-t border-border pt-6">
        <h2 className="font-heading text-sm text-primary">Sobre Sin Línea</h2>
        <Link href="/contacto" className="block font-sans text-sm">
          Contacto
        </Link>
        <Link href="/como-funciona" className="inline-block font-sans text-sm">
          Cómo funciona
        </Link>
      </section>

      <SignOutButton className="mt-10 border border-border bg-hover text-primary hover:bg-surface-secondary" />
    </div>
  );
}
