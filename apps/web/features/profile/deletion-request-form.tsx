"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";

export function DeletionRequestForm() {
  const [message, setMessage] = useState("");
  const [code, setCode] = useState<string | null>(null);
  const [followUp, setFollowUp] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setPending(true);
    setError(null);
    try {
      const response = await fetch("/api/v1/auth/deletion-request", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message }),
      });
      if (response.status === 401) {
        setError("Tenés que iniciar sesión para pedir la eliminación.");
        return;
      }
      if (response.status === 429) {
        setError("Hay demasiados envíos seguidos. Probá más tarde.");
        return;
      }
      if (!response.ok) {
        setError("No pudimos registrar el pedido. El mensaje necesita al menos 20 caracteres.");
        return;
      }
      const payload = (await response.json()) as { public_code: string; follow_up_url: string };
      setCode(payload.public_code);
      setFollowUp(payload.follow_up_url);
      setMessage("");
    } catch {
      setError("No pudimos registrar el pedido.");
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="max-w-md space-y-3">
      <p className="font-sans text-sm text-secondary">
        El pedido usa el email de esta sesión y queda como un caso para revisarlo. No borra la cuenta
        al enviarlo. Guardá el enlace de seguimiento.
      </p>
      <label className="block font-sans text-sm text-secondary" htmlFor="deletion-message">
        Qué querés que eliminemos
        <textarea
          id="deletion-message"
          value={message}
          onChange={(event) => setMessage(event.target.value)}
          required
          minLength={20}
          rows={4}
          className="sl-input mt-1"
        />
      </label>
      {code ? (
        <p className="font-sans text-sm text-secondary">
          Pedido {code}.{" "}
          {followUp ? (
            <Link href={followUp} className="underline">
              Seguir el caso
            </Link>
          ) : null}
        </p>
      ) : null}
      {error ? (
        <p role="alert" className="font-sans text-sm text-accent-ochre">
          {error}
        </p>
      ) : null}
      <button type="submit" disabled={pending} className="border border-border px-3 py-2 font-sans text-sm text-primary">
        {pending ? "Enviando…" : "Pedir eliminación"}
      </button>
    </form>
  );
}
