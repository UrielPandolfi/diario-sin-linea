"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";

export function PasswordResetConfirmForm({ token }: { token: string }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [done, setDone] = useState(false);
  const [noticeSent, setNoticeSent] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setPending(true);
    setError(null);
    try {
      const response = await fetch("/api/v1/auth/password-reset/confirm", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, password }),
      });
      if (response.status === 400) {
        setError("El enlace no sirve, venció o ya se usó. Pedí uno nuevo.");
        return;
      }
      if (!response.ok) {
        setError("No pudimos guardar la contraseña.");
        return;
      }
      const payload = (await response.json()) as { security_notice_sent?: boolean };
      setNoticeSent(payload.security_notice_sent === true);
      setDone(true);
    } catch {
      setError("No pudimos guardar la contraseña.");
    } finally {
      setPending(false);
    }
  }

  if (done) {
    return (
      <div className="mt-8 max-w-sm space-y-4">
        <p className="font-sans text-sm text-secondary">
          Guardamos la contraseña nueva. Este enlace no abre la sesión: entrá con la contraseña que acabás de elegir.
          {noticeSent
            ? " Te enviamos un aviso al email, sin la contraseña."
            : " No salió el aviso por email."}
        </p>
        <Link href="/entrar" className="sl-btn-primary inline-flex">
          Entrar
        </Link>
      </div>
    );
  }

  return (
    <form onSubmit={onSubmit} className="mt-8 max-w-sm space-y-4">
      <label className="block font-sans text-sm text-secondary" htmlFor="new-password">
        Contraseña nueva
        <input
          id="new-password"
          type="password"
          autoComplete="new-password"
          minLength={8}
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          required
          className="sl-input mt-1"
        />
      </label>
      <p className="font-sans text-xs text-muted">Mínimo 8 caracteres. Las sesiones anteriores dejan de servir.</p>
      {error ? (
        <p role="alert" className="font-sans text-sm text-accent-ochre">
          {error}
        </p>
      ) : null}
      <button type="submit" disabled={pending} className="sl-btn-primary disabled:opacity-60">
        {pending ? "Guardando…" : "Guardar contraseña"}
      </button>
    </form>
  );
}
