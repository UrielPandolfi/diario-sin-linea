"use client";

import { createCase, PublicApiError } from "@/lib/api/public";
import { FormEvent, useMemo, useState } from "react";

export const CASE_REASONS: { value: string; label: string }[] = [
  { value: "INCORRECT_FACT", label: "Hay un dato incorrecto." },
  { value: "MISSING_INFO", label: "Falta información importante." },
  { value: "SOURCE_MISREAD", label: "Una fuente está mal interpretada." },
  { value: "CONTRIBUTE_INFO", label: "Quiero aportar información o una fuente." },
  { value: "INVOLVED_RESPONSE", label: "Estoy involucrado y quiero responder." },
  { value: "WHY_WRITTEN", label: "Quiero saber por qué se escribió de esta manera." },
  { value: "WHY_PUBLISHED", label: "Quiero saber por qué se publicó esta noticia." },
  { value: "OTHER", label: "Otro." },
];

function newIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (char) => {
    const rand = (Math.random() * 16) | 0;
    const value = char === "x" ? rand : (rand & 0x3) | 0x8;
    return value.toString(16);
  });
}

export function CaseForm({
  articleId,
  articleSlug,
  reportedVersion,
  storageKey,
}: {
  articleId?: string;
  articleSlug?: string;
  reportedVersion?: number | null;
  storageKey: string;
}) {
  const [reason, setReason] = useState(articleId || articleSlug ? "INCORRECT_FACT" : "OTHER");
  const [message, setMessage] = useState("");
  const [linkUrl, setLinkUrl] = useState("");
  const [email, setEmail] = useState("");
  const [website, setWebsite] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<{ public_code: string; follow_up_url: string } | null>(null);
  const idempotencyKey = useMemo(() => {
    if (typeof window === "undefined") return newIdempotencyKey();
    const existing = sessionStorage.getItem(storageKey);
    if (existing) return existing;
    const created = newIdempotencyKey();
    sessionStorage.setItem(storageKey, created);
    return created;
  }, [storageKey]);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setPending(true);
    setError(null);
    try {
      const result = await createCase(
        {
          article_id: articleId,
          article_slug: articleSlug,
          reported_version_number: reportedVersion ?? undefined,
          reason,
          message,
          link_url: linkUrl.trim() || undefined,
          email: email.trim() || undefined,
          website: website.trim() || undefined,
        },
        idempotencyKey,
      );
      setDone(result);
      sessionStorage.removeItem(storageKey);
    } catch (err) {
      if (err instanceof PublicApiError && err.status === 429) {
        setError("Hay muchos envíos seguidos. Probá de nuevo en un rato.");
      } else {
        setError("No se pudo enviar. Revisá los campos e intentá otra vez.");
      }
    } finally {
      setPending(false);
    }
  }

  if (done) {
    return (
      <div className="mt-4 border border-border bg-surface px-4 py-4">
        <p className="font-heading text-base text-primary">Recibimos tu consulta</p>
        <p className="mt-2 font-sans text-sm text-secondary">
          Código <span className="text-primary">{done.public_code}</span>. Guardá este enlace para
          consultar el estado. No enviamos correos automáticos.
        </p>
        <a
          href={done.follow_up_url}
          rel="noreferrer"
          className="mt-3 inline-block font-sans text-sm text-accent-petrol"
        >
          Abrir seguimiento
        </a>
      </div>
    );
  }

  return (
    <form onSubmit={(event) => void onSubmit(event)} className="mt-4 space-y-3">
      <label className="block font-sans text-sm text-secondary">
        Motivo
        <select
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          className="mt-1 w-full border border-border bg-background px-3 py-2 font-sans text-primary"
          required
        >
          {CASE_REASONS.map((item) => (
            <option key={item.value} value={item.value}>
              {item.label}
            </option>
          ))}
        </select>
      </label>
      <label className="block font-sans text-sm text-secondary">
        Mensaje
        <textarea
          value={message}
          onChange={(event) => setMessage(event.target.value)}
          minLength={20}
          maxLength={4000}
          rows={5}
          required
          className="mt-1 w-full border border-border bg-background px-3 py-2 font-sans text-primary"
        />
      </label>
      <label className="block font-sans text-sm text-secondary">
        Enlace (opcional)
        <input
          type="url"
          value={linkUrl}
          onChange={(event) => setLinkUrl(event.target.value)}
          className="mt-1 w-full border border-border bg-background px-3 py-2 font-sans text-primary"
        />
      </label>
      <label className="block font-sans text-sm text-secondary">
        Email (opcional, por si queremos escribirte). El seguimiento es por el enlace; no enviamos
        correos automáticos.
        <input
          type="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          className="mt-1 w-full border border-border bg-background px-3 py-2 font-sans text-primary"
        />
      </label>
      <div className="hidden" aria-hidden="true">
        <label>
          Website
          <input value={website} onChange={(event) => setWebsite(event.target.value)} tabIndex={-1} autoComplete="off" />
        </label>
      </div>
      {error ? <p className="font-sans text-sm text-accent-ochre">{error}</p> : null}
      <button
        type="submit"
        disabled={pending}
        className="border border-border bg-hover px-3 py-2 font-sans text-sm text-primary disabled:opacity-60"
      >
        {pending ? "Enviando…" : "Enviar"}
      </button>
    </form>
  );
}