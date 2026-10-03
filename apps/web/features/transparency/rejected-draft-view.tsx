"use client";

import { ArticleBody } from "@/features/article/article-body";
import { SourceList } from "@/features/feed/source-list";
import {
  REASON_CATEGORY_LABEL,
  REJECTED_DRAFT_MARK,
  REJECTED_DRAFT_WARNING,
  publishedArticlePath,
} from "@/features/transparency/copy";
import type { ArticleBodyBlock, ArticleClaim, ArticleSource } from "@/lib/api/types";
import { PublicApiError } from "@/lib/api/public";
import { safeReturnTo } from "@/lib/auth/return-to";
import { CircleDashed, FileQuestion, Gauge, Quote, ShieldAlert, Wrench, type LucideIcon } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

const REASON_MARK: Record<string, { tone: string; Icon: LucideIcon }> = {
  incomplete_verification: { tone: "verify", Icon: CircleDashed },
  missing_support: { tone: "support", Icon: FileQuestion },
  attribution: { tone: "attrib", Icon: Quote },
  overcertainty: { tone: "certain", Icon: Gauge },
  technical: { tone: "tech", Icon: Wrench },
  general: { tone: "general", Icon: ShieldAlert },
};

type DraftDetail = {
  id: string;
  headline: string;
  summary: string;
  body: string;
  body_blocks?: ArticleBodyBlock[] | null;
  label: string;
  evaluated_at: string;
  reason: string;
  reasons: { category: string; text: string }[];
  sources: ArticleSource[];
  claims?: ArticleClaim[];
  published_path: string | null;
};

function formatEvaluatedAt(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("es-AR", {
    day: "numeric",
    month: "long",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

export function RejectedDraftView({ articleId }: { articleId: string }) {
  const [draft, setDraft] = useState<DraftDetail | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "missing" | "error">("loading");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setState("loading");
      try {
        const response = await fetch(`/api/v1/transparency/rejected-drafts/${articleId}`, {
          credentials: "include",
          cache: "no-store",
        });
        if (response.status === 401) {
          const next = safeReturnTo(window.location.pathname, "/transparencia/borradores");
          window.location.assign(`/entrar?next=${encodeURIComponent(next)}`);
          return;
        }
        if (response.status === 404) {
          if (!cancelled) setState("missing");
          return;
        }
        if (!response.ok) {
          throw new PublicApiError("request_failed", response.status);
        }
        const payload = (await response.json()) as DraftDetail;
        if (!cancelled) {
          setDraft(payload);
          setState("ready");
        }
      } catch {
        if (!cancelled) setState("error");
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [articleId]);

  if (state === "loading") {
    return (
      <div aria-busy="true" className="mx-auto max-w-measure px-4 py-10">
        <span className="sr-only">Cargando borrador no aprobado</span>
        <div className="h-40 animate-pulse bg-surface" />
      </div>
    );
  }

  if (state === "error") {
    return (
      <div className="mx-auto max-w-measure px-4 py-16 text-center">
        <p className="font-heading text-base text-primary">No pudimos abrir este borrador.</p>
        <button type="button" onClick={() => window.location.reload()} className="mt-4 font-sans text-sm text-accent">
          Reintentar
        </button>
      </div>
    );
  }

  if (state === "missing" || draft === null) {
    return (
      <div className="mx-auto max-w-measure px-4 py-16">
        <p className="font-heading text-lg text-primary">No encontramos ese borrador.</p>
        <Link href="/transparencia/borradores" className="mt-4 inline-block font-sans text-sm">
          Volver al listado
        </Link>
      </div>
    );
  }

  const published = publishedArticlePath(draft.published_path);
  const update = draft.label === "Actualización no aprobada";

  return (
    <article className="article-root mx-auto w-full max-w-article px-4 py-6 md:px-8 md:py-8">
      <div className="sticky top-0 z-20 -mx-4 border-b border-notice-border bg-notice-bg/90 px-4 py-2 backdrop-blur md:-mx-8 md:px-8">
        <p className="font-sans text-[12px] font-medium uppercase tracking-[0.14em] text-notice-fg">{REJECTED_DRAFT_MARK}</p>
      </div>

      <nav aria-label="Migas de pan" className="mt-4 font-sans text-[13px] text-secondary">
        <Link href="/transparencia" className="text-secondary hover:text-primary">
          Transparencia
        </Link>
        <span aria-hidden className="px-1.5 text-muted">
          /
        </span>
        <Link href="/transparencia/borradores" className="text-secondary hover:text-primary">
          Borradores no aprobados
        </Link>
      </nav>

      <div className="mt-6 max-w-[var(--article-measure)]">
        <p
          role="note"
          className="rounded-2xl border border-notice-border bg-notice-bg px-4 py-3 font-sans text-sm leading-relaxed text-notice-fg shadow-[0_10px_24px_var(--shadow)]"
        >
          {REJECTED_DRAFT_WARNING}
        </p>
        {update ? (
          <p className="mt-4 font-sans text-sm leading-relaxed text-secondary">
            <span className="text-primary">Actualización no aprobada.</span> La noticia publicada no cambia.
            {published ? (
              <>
                {" "}
                <Link href={published}>Ver la versión publicada</Link>
              </>
            ) : null}
          </p>
        ) : null}
        <h1 className="article-title mt-5">{draft.headline}</h1>
        {draft.summary ? <p className="article-dek mt-5">{draft.summary}</p> : null}
        <p className="mt-4 font-sans text-[13px] text-secondary">
          <time dateTime={draft.evaluated_at}>Evaluado el {formatEvaluatedAt(draft.evaluated_at)}</time>
          <span aria-hidden className="px-1.5 text-muted">
            ·
          </span>
          <span>{draft.label}</span>
        </p>

        <section className="sl-block mt-8 p-4 sm:p-5" aria-labelledby="rejection-reasons">
          <h2 id="rejection-reasons" className="font-sans text-[12px] font-medium uppercase tracking-[0.16em] text-notice-fg">
            Por qué no se aprobó
          </h2>
          <ul className="mt-3 space-y-3">
            {draft.reasons.map((reason, index) => {
              const mark = REASON_MARK[reason.category] ?? REASON_MARK.general;
              const Icon = mark.Icon;
              return (
                <li
                  key={`${reason.category}-${reason.text}`}
                  className="sl-reason sl-enter"
                  data-tone={mark.tone}
                  style={{ animationDelay: `${index * 70}ms` }}
                >
                  <span className="sl-reason-icon" aria-hidden>
                    <Icon className="h-4 w-4" strokeWidth={1.8} />
                  </span>
                  <div className="min-w-0 font-sans text-sm leading-relaxed text-secondary">
                    <p className="font-medium text-primary">{REASON_CATEGORY_LABEL[reason.category] ?? "Control editorial"}</p>
                    <p className="mt-1">{reason.text}</p>
                  </div>
                </li>
              );
            })}
          </ul>
        </section>

        <ArticleBody
          body={draft.body}
          bodyBlocks={draft.body_blocks}
          claims={draft.claims}
          sourceKey={`draft:${draft.id}`}
        />

        {draft.sources.length > 0 ? (
          <div className="sl-block mt-10 p-5">
            <h2 className="font-sans text-[12px] font-medium uppercase tracking-[0.16em] text-accent">
              Fuentes de esta versión
            </h2>
            <div className="mt-3">
              <SourceList sources={draft.sources} />
            </div>
          </div>
        ) : null}
      </div>
    </article>
  );
}
