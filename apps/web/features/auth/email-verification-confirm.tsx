"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";

export function EmailVerificationConfirm({ token }: { token: string }) {
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [done, setDone] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setPending(true);
    setError(null);
    try {
      const response = await fetch("/api/v1/auth/email-verification/confirm", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token }),
      });
      if (response.status === 400) {
        setError("El enlace no sirve, venció o ya se usó. Pedí otro desde Perfil.");
        return;
      }
      if (!response.ok) {
        setError("No pudimos confirmar el email.");
        return;
      }
      setDone(true);
    } catch {
      setError("No pudimos confirmar el email.");
    } finally {
      setPending(false);
    }
  }

  if (done) {
    return (
      <div className="mt-8 max-w-sm space-y-4">
        <p className="font-sans text-sm text-secondary">Confirmamos el email. Este enlace no abre una sesión.</p>
        <Link href="/entrar" className="sl-btn-primary">
          Entrar
        </Link>
      </div>
    );
  }

  return (
    <form onSubmit={onSubmit} className="mt-8 max-w-sm space-y-4">
      <p className="font-sans text-sm text-secondary">
        El enlace no se usa solo al abrirlo. Confirmá el email con el botón.
      </p>
      {error ? (
        <p role="alert" className="font-sans text-sm text-accent-ochre">
          {error}
        </p>
      ) : null}
      <button type="submit" disabled={pending} className="sl-btn-primary disabled:opacity-60">
        {pending ? "Confirmando…" : "Confirmar email"}
      </button>
    </form>
  );
}
