"use client";

import { SignOutButton } from "@/features/auth/sign-out-button";
import { LocalitySearch } from "@/features/locality/locality-search";
import { DeletionRequestForm } from "@/features/profile/deletion-request-form";
import { PasswordChangeForm } from "@/features/profile/password-change-form";
import { ThemeToggle } from "@/components/theme-toggle";
import { fetchReaderAccount, placeLabel, type ReaderPlace } from "@/lib/auth/account";
import Link from "next/link";
import { useEffect, useState } from "react";

export function ProfileView() {
  const [place, setPlace] = useState<ReaderPlace | null>(null);
  const [email, setEmail] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    void fetchReaderAccount()
      .then((account) => {
        setEmail(account.email);
        setPlace(account.locality);
      })
      .finally(() => setReady(true));
  }, []);

  if (!ready) {
    return <div className="h-40 animate-pulse bg-surface" />;
  }

  return (
    <div className="mx-auto min-h-screen max-w-measure px-4 py-8 md:px-6">
      <p className="font-sans text-[12px] uppercase tracking-[0.16em] text-accent">Perfil</p>
      <h1 className="mt-2 font-heading text-3xl font-semibold text-primary">Tu espacio</h1>
      <p className="mt-2 font-sans text-sm text-secondary">
        {email ? email : "Tu cuenta"}
      </p>

      <section className="sl-block sl-enter mt-8 space-y-3 p-5">
        <h2 className="font-heading text-sm text-primary">Localidad</h2>
        <p className="font-sans text-sm text-secondary">
          {place
            ? `${placeLabel(place)}. La usamos para mostrarte noticias cercanas.`
            : "Todavía no elegiste una localidad. La usamos para mostrarte noticias cercanas."}
        </p>
        <div className="max-w-md">
          <LocalitySearch mode="edit" showClear={place !== null} onChanged={setPlace} />
        </div>
      </section>

      <section className="sl-block mt-4 space-y-3 p-5">
        <h2 className="font-heading text-sm text-primary">Guardados</h2>
        <Link href="/guardados" className="sl-link-row font-sans text-sm">
          Ver notas guardadas
        </Link>
      </section>

      <section className="sl-block mt-4 space-y-3 p-5">
        <h2 className="font-heading text-sm text-primary">Contraseña</h2>
        <PasswordChangeForm />
      </section>

      <section className="sl-block mt-4 space-y-3 p-5">
        <h2 className="font-heading text-sm text-primary">Apariencia</h2>
        <ThemeToggle variant="labeled" />
      </section>

      <section className="sl-block mt-4 space-y-1 p-5">
        <h2 className="font-heading text-sm text-primary">Sobre Sin Línea</h2>
        <Link href="/contacto" className="sl-link-row font-sans text-sm">
          Contacto
        </Link>
        <Link href="/como-funciona" className="sl-link-row font-sans text-sm">
          Cómo funciona
        </Link>
        <Link href="/privacidad" className="sl-link-row font-sans text-sm">
          Privacidad
        </Link>
        <Link href="/terminos" className="sl-link-row font-sans text-sm">
          Términos y condiciones
        </Link>
        <Link href="/transparencia" className="sl-link-row font-sans text-sm">
          Transparencia
        </Link>
      </section>

      <section className="sl-block mt-4 space-y-3 p-5">
        <h2 className="font-heading text-sm text-primary">Eliminar cuenta</h2>
        <DeletionRequestForm />
      </section>

      <SignOutButton className="mt-10 border border-border bg-hover text-primary hover:bg-surface-secondary" />
    </div>
  );
}
