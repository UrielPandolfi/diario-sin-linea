"use client";

import { LocalitySelector } from "@/features/locality/locality-selector";
import { ThemeToggle } from "@/components/theme-toggle";
import { clearLocalityCookie, readLocalityCookie } from "@/lib/locality";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

export function ProfileView() {
  const router = useRouter();
  const [locality, setLocality] = useState<string | null>(null);

  useEffect(() => {
    setLocality(readLocalityCookie());
  }, []);

  function leave() {
    clearLocalityCookie();
    router.push("/entrar");
    router.refresh();
  }

  if (!locality) {
    return <div className="h-40 animate-pulse bg-surface" />;
  }

  return (
    <div className="mx-auto min-h-screen max-w-2xl border-x border-border px-4 py-8 md:px-6">
      <p className="font-heading text-xs uppercase tracking-[0.16em] text-accent-ochre">Perfil</p>
      <h1 className="mt-2 font-heading text-2xl text-primary">Tu espacio</h1>
      <p className="mt-2 font-sans text-sm text-secondary">
        Todavía no hay cuentas. Guardamos solo tu localidad en este dispositivo.
      </p>

      <section className="mt-8 space-y-2 border-t border-border pt-6">
        <h2 className="font-heading text-sm text-primary">Localidad</h2>
        <LocalitySelector current={locality} onSaved={setLocality} />
      </section>

      <section className="mt-8 space-y-3 border-t border-border pt-6">
        <h2 className="font-heading text-sm text-primary">Apariencia</h2>
        <ThemeToggle />
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

      <section className="mt-8 space-y-2 border-t border-border pt-6">
        <h2 className="font-heading text-sm text-muted">Cuenta</h2>
        <p className="font-sans text-sm text-muted">Nombre, avatar y preferencias · Próximamente</p>
      </section>

      <button
        type="button"
        onClick={leave}
        className="mt-10 border border-border bg-hover px-3 py-2 font-sans text-sm text-primary hover:bg-surface-secondary"
      >
        Salir
      </button>
    </div>
  );
}
