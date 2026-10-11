"use client";

import { SignOutButton } from "@/features/auth/sign-out-button";
import { LocalitySearch } from "@/features/locality/locality-search";
import { DeletionRequestForm } from "@/features/profile/deletion-request-form";
import { EmailVerification } from "@/features/profile/email-verification";
import { PasswordChangeForm } from "@/features/profile/password-change-form";
import { ThemeToggle } from "@/components/theme-toggle";
import { fetchReaderAccount, placeLabel, saveReaderUsername, type ReaderPlace } from "@/lib/auth/account";
import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";

function UsernameForm({ onSaved }: { onSaved: (username: string, avatarUrl: string | null) => void }) {
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setPending(true);
    setError(null);
    try {
      const saved = await saveReaderUsername(value);
      onSaved(saved.username, saved.avatar_url);
    } catch (caught) {
      const code = caught instanceof Error ? caught.message : "";
      setError(
        code === "taken"
          ? "Ese nombre de usuario ya está en uso."
          : "Usá de 3 a 20 letras, números o _.",
      );
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-1 flex-col gap-2">
      <label className="font-sans text-sm text-secondary" htmlFor="profile-username">
        Nombre de usuario
        <input
          id="profile-username"
          value={value}
          onChange={(event) => setValue(event.target.value)}
          required
          minLength={3}
          maxLength={20}
          pattern="[A-Za-z0-9_]{3,20}"
          className="sl-input mt-1"
        />
      </label>
      {error ? (
        <p role="alert" className="font-sans text-sm text-accent-ochre">
          {error}
        </p>
      ) : null}
      <button type="submit" disabled={pending} className="sl-btn w-fit disabled:opacity-60">
        {pending ? "Guardando…" : "Guardar nombre"}
      </button>
    </form>
  );
}

export function ProfileView() {
  const [place, setPlace] = useState<ReaderPlace | null>(null);
  const [email, setEmail] = useState<string | null>(null);
  const [emailVerified, setEmailVerified] = useState<boolean | null>(null);
  const [username, setUsername] = useState<string | null>(null);
  const [avatarUrl, setAvatarUrl] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    void fetchReaderAccount()
      .then((account) => {
        setEmail(account.email);
        setEmailVerified(account.email_verified);
        setUsername(account.username);
        setAvatarUrl(account.avatar_url);
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
        <h2 className="font-heading text-sm text-primary">Nombre público</h2>
        <div className="flex items-center gap-3">
          {avatarUrl ? (
            <img src={avatarUrl} alt="" width={48} height={48} className="h-12 w-12 rounded-full object-cover" />
          ) : (
            <span className="h-12 w-12 rounded-full bg-surface-secondary" aria-hidden />
          )}
          {username ? (
            <p className="font-sans text-sm text-primary">{username}</p>
          ) : (
            <UsernameForm
              onSaved={(next, photo) => {
                setUsername(next);
                setAvatarUrl(photo);
              }}
            />
          )}
        </div>
        <p className="font-sans text-sm text-secondary">
          {avatarUrl
            ? "La foto se genera al verificar el correo. El nombre se muestra en los comentarios que no marques como anónimos."
            : "Al verificar el correo se genera una foto ilustrada. El nombre se muestra en los comentarios que no marques como anónimos."}
        </p>
      </section>

      {email && emailVerified !== null ? (
        <section className="sl-block mt-4 space-y-3 p-5">
          <h2 className="font-heading text-sm text-primary">Correo</h2>
          <EmailVerification email={email} verified={emailVerified} />
        </section>
      ) : null}

      <section className="sl-block mt-4 space-y-3 p-5">
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
