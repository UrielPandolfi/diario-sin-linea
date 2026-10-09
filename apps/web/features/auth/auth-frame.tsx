"use client";

import { AuthStage } from "@/features/auth/auth-stage";
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
  const [mailNote, setMailNote] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const register = mode === "register";
  const destination = safeReturnTo(next, "/");

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setPending(true);
    setError(null);
    setMailNote(null);
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
      const body = (await response.json()) as { locality_step?: string; email_verification?: string };
      if (register && body.email_verification === "failed") {
        setMailNote("La cuenta quedó creada, pero no salió el correo de confirmación. Podés reenviarlo desde Perfil.");
        return;
      }
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
    <AuthStage>
          <p className="font-heading text-xs uppercase tracking-[0.16em] text-accent">
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
            {register ? (
              <p className="font-sans text-xs text-muted">
                Mínimo 8 caracteres. Al crear la cuenta aceptás los{" "}
                <Link href="/terminos" className="underline">
                  Términos
                </Link>{" "}
                y la{" "}
                <Link href="/privacidad" className="underline">
                  Privacidad
                </Link>
                .
              </p>
            ) : (
              <p className="font-sans text-xs text-muted">
                <Link href="/cuenta/recuperar" className="underline">
                  Olvidé mi contraseña
                </Link>
              </p>
            )}
            {mailNote ? (
              <p className="font-sans text-sm text-secondary">
                {mailNote}{" "}
                <Link href={`/onboarding?next=${encodeURIComponent(destination)}`} className="underline">
                  Continuar
                </Link>
              </p>
            ) : null}
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
    </AuthStage>
  );
}
