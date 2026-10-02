"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";

export function PasswordResetRequestForm() {
  const [email, setEmail] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setPending(true);
    setMessage(null);
    setError(null);
    try {
      const response = await fetch("/api/v1/auth/password-reset/request", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      });
      if (response.status === 503) {
        setError("El correo de restablecimiento no está configurado. Escribinos desde Contacto con el email de la cuenta.");
        return;
      }
      if (response.status === 429) {
        setError("Hay demasiados pedidos seguidos. Probá más tarde.");
        return;
      }
      if (!response.ok) {
        setError("No pudimos tomar el pedido. Revisá el email e intentá de nuevo.");
        return;
      }
      const payload = (await response.json()) as { detail?: string };
      setMessage(payload.detail ?? "Si hay una cuenta con ese email, enviamos un enlace para elegir una contraseña nueva.");
    } catch {
      setError("No pudimos tomar el pedido.");
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="mt-8 max-w-sm space-y-4">
      <label className="block font-sans text-sm text-secondary" htmlFor="reset-email">
        Email de la cuenta
        <input
          id="reset-email"
          type="email"
          autoComplete="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          required
          className="sl-input mt-1"
        />
      </label>
      {message ? <p className="font-sans text-sm text-secondary">{message}</p> : null}
      {error ? (
        <p role="alert" className="font-sans text-sm text-accent-ochre">
          {error}{" "}
          {error.includes("Contacto") ? (
            <Link href="/contacto" className="underline">
              Ir a Contacto
            </Link>
          ) : null}
        </p>
      ) : null}
      <button type="submit" disabled={pending} className="sl-btn-primary disabled:opacity-60">
        {pending ? "Enviando…" : "Enviar enlace"}
      </button>
    </form>
  );
}
