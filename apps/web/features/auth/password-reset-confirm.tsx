"use client";

import { safeReturnTo } from "@/lib/auth/return-to";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";

export function PasswordResetConfirmForm({ token }: { token: string }) {
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

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
      if (!response.ok) {
        setError("El enlace no sirve, venció o ya se usó. Pedí uno nuevo.");
        return;
      }
      router.push(safeReturnTo("/", "/"));
      router.refresh();
    } catch {
      setError("No pudimos guardar la contraseña.");
    } finally {
      setPending(false);
    }
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
