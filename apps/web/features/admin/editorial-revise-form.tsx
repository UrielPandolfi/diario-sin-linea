"use client";

import { adminFetch, type AdminEventDetail } from "@/lib/admin";
import { FormEvent, useEffect, useState } from "react";

export function EditorialReviseForm({
  eventId,
  detail,
  onDone,
}: {
  eventId: string;
  detail: AdminEventDetail;
  onDone: (message: string) => void;
}) {
  const live = detail.live;
  const [kind, setKind] = useState<"MINOR" | "UPDATE" | "CORRECTION">("CORRECTION");
  const [headline, setHeadline] = useState(live?.headline ?? "");
  const [summary, setSummary] = useState(live?.summary ?? "");
  const [body, setBody] = useState(live?.body ?? "");
  const [notice, setNotice] = useState("");
  const [showNearTitle, setShowNearTitle] = useState(true);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setHeadline(live?.headline ?? "");
    setSummary(live?.summary ?? "");
    setBody(live?.body ?? "");
  }, [live?.headline, live?.summary, live?.body, live?.version_number]);

  if (!live) {
    return <p className="px-4 py-4 font-sans text-sm text-secondary">No hay versión publicada para editar.</p>;
  }

  const liveVersionNumber = live.version_number;
  const draftPending =
    detail.article != null &&
    detail.article.published_version != null &&
    detail.article.current_version !== detail.article.published_version;

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setPending(true);
    setError(null);
    try {
      const response = await adminFetch(`/api/v1/admin/events/${eventId}/editorial-revise`, {
        method: "POST",
        body: JSON.stringify({
          base_published_version: liveVersionNumber,
          kind,
          headline,
          summary,
          body,
          public_notice: kind === "MINOR" ? undefined : notice,
          show_near_title: kind === "CORRECTION" ? showNearTitle : false,
        }),
      });
      if (response.status === 409) {
        setError("La versión publicada cambió. Recargá el suceso antes de editar.");
        return;
      }
      if (!response.ok) {
        const detailText = await response.text();
        throw new Error(detailText || `Error ${response.status}`);
      }
      const payload = (await response.json()) as { correction_id?: string | null; kind?: string };
      onDone(
        payload.correction_id
          ? `Publicada v${liveVersionNumber + 1}. Corrección ${payload.correction_id}.`
          : "Ajuste menor publicado.",
      );
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "No se pudo publicar la revisión.");
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={(event) => void onSubmit(event)} className="space-y-3 px-4 py-4">
      {draftPending ? (
        <p className="font-sans text-sm text-accent-ochre">
          Hay un borrador de pipeline (v{detail.article?.current_version}) distinto de la live (v
          {live.version_number}). Este editor parte de la live.
        </p>
      ) : null}
      <label className="block font-sans text-sm text-secondary">
        Tipo
        <select
          value={kind}
          onChange={(event) => setKind(event.target.value as "MINOR" | "UPDATE" | "CORRECTION")}
          className="mt-1 w-full border border-border bg-background px-3 py-2 text-primary"
        >
          <option value="MINOR">Ajuste menor (sin aviso público)</option>
          <option value="UPDATE">Actualización</option>
          <option value="CORRECTION">Corrección</option>
        </select>
      </label>
      <p className="font-sans text-xs text-muted">No uses ajuste menor para un cambio de dato.</p>
      <label className="block font-sans text-sm text-secondary">
        Titular
        <input
          value={headline}
          onChange={(event) => setHeadline(event.target.value)}
          className="mt-1 w-full border border-border bg-background px-3 py-2 text-primary"
          required
        />
      </label>
      <label className="block font-sans text-sm text-secondary">
        Bajada
        <textarea
          value={summary}
          onChange={(event) => setSummary(event.target.value)}
          rows={3}
          className="mt-1 w-full border border-border bg-background px-3 py-2 text-primary"
          required
        />
      </label>
      <label className="block font-sans text-sm text-secondary">
        Cuerpo
        <textarea
          value={body}
          onChange={(event) => setBody(event.target.value)}
          rows={12}
          className="mt-1 w-full border border-border bg-background px-3 py-2 text-primary"
          required
        />
      </label>
      {kind !== "MINOR" ? (
        <label className="block font-sans text-sm text-secondary">
          Aviso al lector
          <textarea
            value={notice}
            onChange={(event) => setNotice(event.target.value)}
            minLength={20}
            rows={4}
            required
            className="mt-1 w-full border border-border bg-background px-3 py-2 text-primary"
          />
        </label>
      ) : null}
      {kind === "CORRECTION" ? (
        <label className="flex items-center gap-2 font-sans text-sm text-secondary">
          <input
            type="checkbox"
            checked={showNearTitle}
            onChange={(event) => setShowNearTitle(event.target.checked)}
          />
          El cambio altera el sentido de la noticia (mostrar aviso junto al título)
        </label>
      ) : null}
      {error ? <p className="font-sans text-sm text-accent-ochre">{error}</p> : null}
      <button
        type="submit"
        disabled={pending}
        className="border border-border bg-hover px-3 py-2 font-sans text-sm text-primary disabled:opacity-60"
      >
        {pending ? "Publicando…" : "Publicar revisión"}
      </button>
    </form>
  );
}

export function HoldOverrideForm({
  eventId,
  detail,
  onDone,
}: {
  eventId: string;
  detail: AdminEventDetail;
  onDone: (message: string) => void;
}) {
  const [pending, setPending] = useState(false);
  if (!detail.article?.editorial_hold || !detail.live) return null;
  const target = detail.article.current_version;
  const base = detail.article.published_version;
  if (base == null || target === base) return null;

  async function onOverride() {
    setPending(true);
    try {
      const response = await adminFetch(`/api/v1/admin/events/${eventId}/publish`, {
        method: "POST",
        body: JSON.stringify({
          override_editorial_hold: true,
          target_version: target,
          base_published_version: base,
        }),
      });
      if (!response.ok) {
        const text = await response.text();
        throw new Error(text || `Error ${response.status}`);
      }
      onDone("Override de hold: se publicó el borrador del pipeline. Los avisos se conservan.");
    } catch (err: unknown) {
      onDone(err instanceof Error ? err.message : "No se pudo publicar el override.");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="mt-3 border border-border px-3 py-3">
      <p className="font-sans text-sm text-accent-ochre">
        Hold editorial activo. Publicar el borrador v{target} reemplaza el texto live (v{base}) y
        no borra avisos.
      </p>
      <button
        type="button"
        disabled={pending}
        onClick={() => void onOverride()}
        className="mt-2 border border-border bg-hover px-3 py-1.5 font-sans text-sm text-primary disabled:opacity-60"
      >
        {pending ? "Publicando…" : "Publicar borrador con override"}
      </button>
    </div>
  );
}