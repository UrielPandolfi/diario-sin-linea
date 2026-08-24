"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";

export default function AdminLoginPage() {
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setPending(true);
    setError(null);
    try {
      const response = await fetch("/api/v1/admin/login", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password }),
      });
      if (!response.ok) {
        setError("Contraseña incorrecta.");
        return;
      }
      router.push("/admin");
      router.refresh();
    } catch {
      setError("No se pudo conectar con la API.");
    } finally {
      setPending(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-6">
      <p className="font-heading text-sm font-medium uppercase tracking-[0.18em] text-accent-ochre">
        Admin
      </p>
      <h1 className="mt-3 font-heading text-3xl font-medium text-primary">Entrar a redacción</h1>
      <p className="mt-2 font-sans text-secondary">
        Cookie de sesión. No hay usuarios: solo la contraseña de Admin.
      </p>
      <form onSubmit={onSubmit} className="mt-8 space-y-4 border border-border bg-surface p-5">
        <label className="block font-sans text-sm text-secondary">
          Contraseña
          <input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            className="mt-1 w-full border border-border bg-background px-3 py-2 font-sans text-primary"
            autoComplete="current-password"
            required
          />
        </label>
        {error ? <p className="font-sans text-sm text-accent-ochre">{error}</p> : null}
        <button
          type="submit"
          disabled={pending}
          className="w-full border border-border bg-hover px-3 py-2 font-sans text-sm text-primary disabled:opacity-60"
        >
          {pending ? "Entrando…" : "Entrar"}
        </button>
      </form>
    </main>
  );
}
