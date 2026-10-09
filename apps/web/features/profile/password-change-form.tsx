"use client";

import { FormEvent, useState } from "react";

export function PasswordChangeForm() {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setPending(true);
    setMessage(null);
    setError(null);
    try {
      const response = await fetch("/api/v1/auth/password", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
      });
      if (response.status === 401) {
        setError("La contraseña actual no coincide.");
        return;
      }
      if (!response.ok) {
        setError("No pudimos cambiar la contraseña. Tiene que ser distinta y tener al menos 8 caracteres.");
        return;
      }
      const payload = (await response.json()) as { security_notice_sent?: boolean };
      setCurrentPassword("");
      setNewPassword("");
      setMessage(
        payload.security_notice_sent
          ? "Contraseña actualizada. Las otras sesiones quedaron cerradas. Te enviamos un aviso al email, sin la contraseña."
          : "Contraseña actualizada. Las otras sesiones quedaron cerradas. No salió el aviso por email.",
      );
    } catch {
      setError("No pudimos cambiar la contraseña.");
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="max-w-sm space-y-3">
      <label className="block font-sans text-sm text-secondary" htmlFor="current-password">
        Contraseña actual
        <input
          id="current-password"
          type="password"
          autoComplete="current-password"
          value={currentPassword}
          onChange={(event) => setCurrentPassword(event.target.value)}
          required
          className="sl-input mt-1"
        />
      </label>
      <label className="block font-sans text-sm text-secondary" htmlFor="profile-new-password">
        Contraseña nueva
        <input
          id="profile-new-password"
          type="password"
          autoComplete="new-password"
          minLength={8}
          value={newPassword}
          onChange={(event) => setNewPassword(event.target.value)}
          required
          className="sl-input mt-1"
        />
      </label>
      {message ? <p className="font-sans text-sm text-secondary">{message}</p> : null}
      {error ? (
        <p role="alert" className="font-sans text-sm text-accent-ochre">
          {error}
        </p>
      ) : null}
      <button type="submit" disabled={pending} className="sl-btn-primary disabled:opacity-60">
        {pending ? "Guardando…" : "Cambiar contraseña"}
      </button>
    </form>
  );
}
