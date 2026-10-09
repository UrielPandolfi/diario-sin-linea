"use client";

import { FormEvent, useState } from "react";

export function EmailVerification({ email, verified }: { email: string; verified: boolean }) {
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setPending(true);
    setMessage(null);
    setError(null);
    try {
      const response = await fetch("/api/v1/auth/email-verification/request", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      });
      if (response.status === 503) {
        setError("El correo de confirmación no está configurado.");
        return;
      }
      if (response.status === 429) {
        setError("Hay demasiados pedidos seguidos. Probá más tarde.");
        return;
      }
      if (!response.ok) {
        setError("No pudimos tomar el pedido.");
        return;
      }
      const payload = (await response.json()) as { detail?: string };
      setMessage(
        payload.detail ??
          "Si la cuenta sigue sin confirmar y el correo sale, llega un enlace. Si no llega, el envío no se completó.",
      );
    } catch {
      setError("No pudimos tomar el pedido.");
    } finally {
      setPending(false);
    }
  }

  if (verified) {
    return <p className="font-sans text-sm text-secondary">Este email está confirmado.</p>;
  }

  return (
    <form onSubmit={onSubmit} className="space-y-3">
      <p className="font-sans text-sm text-secondary">
        Todavía no confirmaste este email. Podés usar la cuenta igual. El enlace vence a las 24 horas y sirve una sola vez.
      </p>
      {message ? <p className="font-sans text-sm text-secondary">{message}</p> : null}
      {error ? (
        <p role="alert" className="font-sans text-sm text-accent-ochre">
          {error}
        </p>
      ) : null}
      <button type="submit" disabled={pending} className="sl-btn-primary max-w-sm disabled:opacity-60">
        {pending ? "Enviando…" : "Reenviar confirmación"}
      </button>
    </form>
  );
}
