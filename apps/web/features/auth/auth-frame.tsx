"use client";

import { BrandMark } from "@/features/shell/brand-mark";
import { loginPath, registerPath, safeReturnTo } from "@/lib/auth/return-to";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";

export function AuthFrame({
  mode,
  next,
}: {
  mode: "login" | "register";
  next: string | null;
}) {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const register = mode === "register";
  const destination = safeReturnTo(next, "/");

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setPending(true);
    setError(null);
    try {
      const response = await fetch(register ? "/api/v1/auth/register" : "/api/v1/auth/login", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      if (response.status === 401) {
        setError("Email o contraseña incorrectos.");
        return;
      }
      if (response.status === 409) {
        setError("Ese email ya tiene cuenta.");
        return;
      }
      if (response.status === 422) {
        setError("Revisá el email y usá una contraseña de al menos 8 caracteres.");
        return;
      }
      if (!response.ok) {
        setError("No se pudo conectar con la API.");
        return;
      }
      const body = (await response.json()) as { locality_step?: string };
      const askLocality = register || body.locality_step === "pending";
      router.push(askLocality ? `/onboarding?next=${encodeURIComponent(destination)}` : destination);
      router.refresh();
    } catch {
      setError("No se pudo conectar con la API.");
    } finally {
      setPending(false);
    }
  }

  return (
    <main className="min-h-screen bg-background">
      <div className="mx-auto grid min-h-screen max-w-[1100px] lg:grid-cols-[minmax(0,1.1fr)_minmax(0,0.9fr)]">
        <section className="flex flex-col justify-between px-8 py-10 md:px-14 md:py-16">
          <div className="flex items-center gap-2 text-primary">
            <BrandMark className="h-9 w-9" />
            <span className="font-heading text-sm font-medium uppercase tracking-[0.18em]">Sin Línea</span>
          </div>
          <div className="max-w-md py-16 lg:py-0">
            <h1 className="font-heading text-4xl font-semibold leading-[1.08] tracking-tight text-primary md:text-5xl">
              Entendé qué está pasando.
            </h1>
            <p className="mt-5 max-w-sm font-sans text-base leading-relaxed text-secondary">
              Información basada en hechos, fuentes y evidencia.
            </p>
          </div>
          <p className="hidden font-sans text-xs text-muted lg:block">Medio informativo centrado en sucesos.</p>
        </section>

        <section className="flex flex-col justify-center border-t border-border px-8 py-12 lg:border-l lg:border-t-0 lg:px-14">
          <p className="font-heading text-xs uppercase tracking-[0.16em] text-muted">
            {register ? "Cuenta nueva" : "Ingreso"}
          </p>
          <h2 className="mt-3 font-heading text-2xl font-medium text-primary">
            {register ? "Crear cuenta" : "Ingresá a Sin Línea"}
          </h2>
          <p className="mt-2 max-w-xs font-sans text-sm text-secondary">
            {register
              ? "Con una cuenta podés entrar al inicio."
              : "El inicio y tu espacio personal necesitan una sesión."}
          </p>
          <form onSubmit={onSubmit} className="mt-8 max-w-sm space-y-4">
            <label className="block font-sans text-sm text-secondary" htmlFor="reader-email">
              Email
              <input
                id="reader-email"
                type="email"
                autoComplete="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                required
                className="sl-input mt-1"
              />
            </label>
            <label className="block font-sans text-sm text-secondary" htmlFor="reader-password">
              Contraseña
              <input
                id="reader-password"
                type="password"
                autoComplete={register ? "new-password" : "current-password"}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
                minLength={8}
                className="sl-input mt-1"
              />
            </label>
            {register ? <p className="font-sans text-xs text-muted">Mínimo 8 caracteres.</p> : null}
            {error ? (
              <p role="alert" className="font-sans text-sm text-accent-ochre">
                {error}
              </p>
            ) : null}
            <button type="submit" disabled={pending} className="sl-btn-primary disabled:opacity-60">
              {pending ? (register ? "Creando…" : "Entrando…") : register ? "Crear cuenta" : "Entrar"}
            </button>
          </form>
          <p className="mt-6 font-sans text-sm text-secondary">
            {register ? (
              <Link href={loginPath(destination)}>Ya tengo cuenta</Link>
            ) : (
              <Link href={registerPath(destination)}>Crear cuenta</Link>
            )}
          </p>
        </section>
      </div>
    </main>
  );
}
