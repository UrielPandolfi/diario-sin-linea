"use client";

import { adminFetch, adminJson, formatWhen } from "@/lib/admin";
import Link from "next/link";
import { useParams } from "next/navigation";
import { FormEvent, useCallback, useEffect, useState } from "react";

type CaseDetail = {
  id: string;
  public_code: string;
  status: string;
  reason: string;
  outcome: string | null;
  message: string;
  link_url: string | null;
  email: string | null;
  public_resolution: string | null;
  created_at: string | null;
  reviewing_at: string | null;
  resolved_at: string | null;
  article_id: string | null;
  article_slug: string | null;
  headline: string | null;
  follow_up_url: string;
  linked_correction_id: string | null;
  reported_version: {
    version_number: number;
    headline: string;
    summary: string;
    body: string;
    published_at: string | null;
  } | null;
  actions: {
    id: string;
    action_type: string;
    actor: string;
    internal_note: string | null;
    created_at: string | null;
  }[];
};

const OUTCOMES = [
  { value: "CORRECTED", label: "Corregido" },
  { value: "UPDATED", label: "Actualizado" },
  { value: "RESPONSE_INCORPORATED", label: "Respuesta incorporada" },
  { value: "NO_CHANGE", label: "Sin cambios" },
  { value: "INQUIRY_ANSWERED", label: "Consulta respondida" },
];

export default function AdminCaseDetailPage() {
  const params = useParams<{ id: string }>();
  const [row, setRow] = useState<CaseDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [outcome, setOutcome] = useState("NO_CHANGE");
  const [resolution, setResolution] = useState("");
  const [correctionId, setCorrectionId] = useState("");

  const load = useCallback(async () => {
    setRow(await adminJson<CaseDetail>(`/api/v1/admin/cases/${params.id}`));
  }, [params.id]);

  useEffect(() => {
    void load().catch((err: unknown) => {
      setError(err instanceof Error ? err.message : "No se pudo cargar el caso.");
    });
  }, [load]);

  async function onReview() {
    const response = await adminFetch(`/api/v1/admin/cases/${params.id}/review`, { method: "POST" });
    if (!response.ok) throw new Error(await response.text());
    setNotice("Pasó a revisión.");
    await load();
  }

  async function onNote(event: FormEvent) {
    event.preventDefault();
    const response = await adminFetch(`/api/v1/admin/cases/${params.id}/notes`, {
      method: "POST",
      body: JSON.stringify({ note }),
    });
    if (!response.ok) throw new Error(await response.text());
    setNote("");
    setNotice("Nota guardada.");
    await load();
  }

  async function onResolve(event: FormEvent) {
    event.preventDefault();
    const needsCorrection = ["CORRECTED", "UPDATED", "RESPONSE_INCORPORATED"].includes(outcome);
    const response = await adminFetch(`/api/v1/admin/cases/${params.id}/resolve`, {
      method: "POST",
      body: JSON.stringify({
        outcome,
        public_resolution: resolution,
        linked_correction_id: needsCorrection && correctionId ? correctionId : null,
      }),
    });
    if (!response.ok) throw new Error(await response.text());
    setNotice("Caso resuelto.");
    await load();
  }

  if (!row) {
    return <p className="font-sans text-sm text-secondary">{error ?? "Cargando…"}</p>;
  }

  const needsCorrection = ["CORRECTED", "UPDATED", "RESPONSE_INCORPORATED"].includes(outcome);

  return (
    <main className="space-y-6">
      <Link href="/admin/cases" className="font-sans text-sm text-secondary">
        ← Casos
      </Link>
      <div>
        <p className="font-heading text-sm uppercase tracking-[0.18em] text-accent-ochre">{row.public_code}</p>
        <h1 className="mt-2 font-heading text-3xl text-primary">{row.reason}</h1>
        <p className="mt-2 font-sans text-sm text-secondary">
          {row.status}
          {row.outcome ? ` · ${row.outcome}` : ""} · {formatWhen(row.created_at)}
        </p>
      </div>
      {notice ? <p className="font-sans text-sm text-primary">{notice}</p> : null}
      {error ? <p className="font-sans text-sm text-accent-ochre">{error}</p> : null}

      <section className="border border-border bg-surface px-4 py-4">
        <p className="whitespace-pre-wrap font-sans text-sm text-primary">{row.message}</p>
        {row.link_url ? (
          <p className="mt-3 font-sans text-sm text-secondary">
            Enlace aportado: <span className="break-all text-primary">{row.link_url}</span>
          </p>
        ) : null}
        {row.email ? <p className="mt-2 font-sans text-sm text-secondary">Email: {row.email}</p> : null}
        {row.headline ? (
          <p className="mt-2 font-sans text-sm text-secondary">
            Noticia: {row.headline}
            {row.article_slug ? ` · ${row.article_slug}` : ""}
          </p>
        ) : (
          <p className="mt-2 font-sans text-sm text-secondary">Consulta general</p>
        )}
      </section>

      {row.reported_version ? (
        <section className="border border-border bg-surface px-4 py-4">
          <h2 className="font-heading text-lg text-primary">Versión reportada v{row.reported_version.version_number}</h2>
          <p className="mt-2 font-heading text-base text-primary">{row.reported_version.headline}</p>
          <p className="mt-2 font-sans text-sm text-secondary">{row.reported_version.summary}</p>
          <div className="mt-3 whitespace-pre-wrap font-sans text-sm text-primary">{row.reported_version.body}</div>
        </section>
      ) : null}

      {row.status !== "RESOLVED" ? (
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => void onReview().catch((err: unknown) => setError(err instanceof Error ? err.message : "Error"))}
            className="border border-border bg-hover px-3 py-1.5 font-sans text-sm text-primary"
          >
            Pasar a revisión
          </button>
        </div>
      ) : null}

      <form onSubmit={(event) => void onNote(event)} className="space-y-2 border border-border bg-surface px-4 py-4">
        <h2 className="font-heading text-lg text-primary">Nota interna</h2>
        <textarea
          value={note}
          onChange={(event) => setNote(event.target.value)}
          className="w-full border border-border bg-background px-3 py-2 font-sans text-sm text-primary"
          rows={3}
          required
        />
        <button type="submit" className="border border-border bg-hover px-3 py-1.5 font-sans text-sm text-primary">
          Guardar nota
        </button>
      </form>

      {row.status !== "RESOLVED" ? (
        <form onSubmit={(event) => void onResolve(event)} className="space-y-2 border border-border bg-surface px-4 py-4">
          <h2 className="font-heading text-lg text-primary">Resolver</h2>
          <select
            value={outcome}
            onChange={(event) => setOutcome(event.target.value)}
            className="w-full border border-border bg-background px-3 py-2 font-sans text-sm text-primary"
          >
            {OUTCOMES.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
          <textarea
            value={resolution}
            onChange={(event) => setResolution(event.target.value)}
            minLength={20}
            required
            rows={4}
            placeholder="Explicación para el lector"
            className="w-full border border-border bg-background px-3 py-2 font-sans text-sm text-primary"
          />
          {needsCorrection ? (
            <input
              value={correctionId}
              onChange={(event) => setCorrectionId(event.target.value)}
              placeholder="UUID de la corrección publicada"
              required
              className="w-full border border-border bg-background px-3 py-2 font-sans text-sm text-primary"
            />
          ) : null}
          <button type="submit" className="border border-border bg-hover px-3 py-1.5 font-sans text-sm text-primary">
            Resolver
          </button>
        </form>
      ) : (
        <section className="border border-border bg-surface px-4 py-4">
          <h2 className="font-heading text-lg text-primary">Resolución</h2>
          <p className="mt-2 whitespace-pre-wrap font-sans text-sm text-secondary">{row.public_resolution}</p>
        </section>
      )}

      <section className="border border-border bg-surface px-4 py-4">
        <h2 className="font-heading text-lg text-primary">Acciones</h2>
        <ul className="mt-3 space-y-2">
          {row.actions.map((action) => (
            <li key={action.id} className="font-sans text-sm text-secondary">
              {action.action_type} · {action.actor} · {formatWhen(action.created_at)}
              {action.internal_note ? ` · ${action.internal_note}` : ""}
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}