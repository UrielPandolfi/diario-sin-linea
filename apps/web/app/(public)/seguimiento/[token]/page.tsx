import { fetchFollowUp, PublicApiError } from "@/lib/api/public";
import type { Metadata } from "next";
import { notFound } from "next/navigation";

export const dynamic = "force-dynamic";
export const robots = { index: false, follow: false };

type Params = { token: string };

export async function generateMetadata(): Promise<Metadata> {
  return {
    title: "Seguimiento",
    robots: { index: false, follow: false },
    referrer: "no-referrer",
  };
}

function statusLabel(status: string): string {
  if (status === "RECEIVED") return "Recibido";
  if (status === "REVIEWING") return "En revisión";
  if (status === "RESOLVED") return "Resuelto";
  return status;
}

function outcomeLabel(outcome: string | null): string | null {
  if (!outcome) return null;
  const map: Record<string, string> = {
    CORRECTED: "Corregido",
    UPDATED: "Actualizado",
    RESPONSE_INCORPORATED: "Respuesta incorporada",
    NO_CHANGE: "Sin cambios",
    INQUIRY_ANSWERED: "Consulta respondida",
  };
  return map[outcome] ?? outcome;
}

export default async function SeguimientoPage({ params }: { params: Promise<Params> }) {
  const { token } = await params;
  let payload;
  try {
    payload = await fetchFollowUp(token);
  } catch (error) {
    if (error instanceof PublicApiError && error.status === 404) notFound();
    throw error;
  }

  return (
    <div className="mx-auto min-h-screen max-w-[42rem] border-x border-border px-4 py-8 md:px-6">
      <p className="font-heading text-xs uppercase tracking-[0.16em] text-accent-ochre">Seguimiento</p>
      <h1 className="mt-2 font-heading text-2xl text-primary">{payload.public_code}</h1>
      <p className="mt-3 font-sans text-sm text-secondary">
        {statusLabel(payload.status)}
        {outcomeLabel(payload.outcome) ? ` · ${outcomeLabel(payload.outcome)}` : ""}
      </p>
      {payload.article ? (
        <p className="mt-2 font-sans text-sm text-secondary">
          Noticia:{" "}
          <a href={`/noticias/${payload.article.slug}`} className="text-accent-petrol" rel="noreferrer">
            {payload.article.headline}
          </a>
        </p>
      ) : (
        <p className="mt-2 font-sans text-sm text-secondary">Consulta general</p>
      )}
      {payload.public_resolution ? (
        <div className="mt-6 border border-border bg-surface px-4 py-4">
          <p className="font-heading text-sm text-primary">Respuesta</p>
          <p className="mt-2 whitespace-pre-wrap font-sans text-sm text-secondary">{payload.public_resolution}</p>
        </div>
      ) : (
        <p className="mt-6 font-sans text-sm text-secondary">
          Todavía no hay una resolución. Volvé a este enlace más adelante. No enviamos correos
          automáticos.
        </p>
      )}
    </div>
  );
}