"use client";

import { ArticleBody } from "@/features/article/article-body";
import { PublicHero } from "@/features/article/public-hero";
import { ReadingSizeToggle, useReadingSize } from "@/features/article/reading-controls";
import { formatArticleStamp, readingMinutes } from "@/features/article/reading";
import { ShareButton } from "@/features/article/share-button";
import { CaseForm } from "@/features/cases/case-form";
import { SourceList } from "@/features/feed/source-list";
import { ThemeToggle } from "@/components/theme-toggle";
import { RelativeTime } from "@/components/relative-time";
import type { Article, ArticleHistoryItem, ArticleNotice } from "@/lib/api/types";
import { isMateriallyUpdated } from "@/lib/relative-time";
import { Info } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

function formatNoticeStamp(iso: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("es-AR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

function noticeLabel(kind: string): string {
  if (kind === "CORRECTION" || kind === "correction") return "Corrección";
  return "Actualización";
}

function historyLabel(item: ArticleHistoryItem): string {
  if (item.type === "published") return "Publicado";
  if (item.type === "correction") return "Corrección";
  if (item.type === "update") return "Actualización";
  return "Actualización";
}

function NoticeBlock({ notice }: { notice: ArticleNotice }) {
  const stamp = formatNoticeStamp(notice.occurred_at);
  return (
    <p className="font-sans text-sm leading-relaxed text-secondary">
      <span className="text-primary">
        {noticeLabel(notice.kind)}
        {stamp ? ` — ${stamp}` : ""}.
      </span>{" "}
      {notice.notice}
    </p>
  );
}

function placeKicker(article: Article): string | null {
  const locality = article.locality?.trim() || null;
  const province = article.province?.trim() || null;
  if (locality && province && locality.toLowerCase() !== province.toLowerCase()) {
    return `${locality} · ${province}`;
  }
  return locality || province;
}

export function ArticleView({ article }: { article: Article }) {
  const href = `/noticias/${article.slug}`;
  const updated = isMateriallyUpdated(article.published_at, article.updated_at);
  const [formOpen, setFormOpen] = useState(false);
  const [readingSize, setReadingSize] = useReadingSize();
  const titleNotices = (article.notices ?? []).filter((item) => item.show_near_title);
  const history = article.history ?? [];
  const kicker = placeKicker(article);
  const stamp = formatArticleStamp(article.published_at);
  const minutes = readingMinutes([article.headline, article.summary, article.body]);
  const crumb = article.locality?.trim() || "Noticia";

  return (
    <article className="article-root mx-auto w-full max-w-article px-4 py-6 md:px-8 md:py-8" data-reading-size={readingSize}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <nav aria-label="Migas de pan" className="font-sans text-[13px] text-secondary">
          <Link href="/" className="text-secondary hover:text-primary">
            Inicio
          </Link>
          <span aria-hidden className="px-1.5 text-muted">
            /
          </span>
          <span className="text-primary">{crumb}</span>
        </nav>
        <div className="ml-auto flex items-center gap-1">
          <ReadingSizeToggle value={readingSize} onChange={setReadingSize} />
          <div className="hidden md:block">
            <ThemeToggle />
          </div>
        </div>
      </div>

      <div className="mt-8 grid grid-cols-1 xl:grid-cols-[var(--article-measure)_var(--article-panel)] xl:gap-x-[var(--article-gap)] xl:items-start">
        <header className="min-w-0 max-w-[var(--article-measure)]">
          {kicker ? (
            <p className="font-sans text-[12px] font-medium uppercase tracking-[0.14em] text-muted">{kicker}</p>
          ) : null}
          <h1 className="article-title mt-3">{article.headline}</h1>
          {titleNotices.length > 0 ? (
            <div className="mt-4 space-y-2 rounded-xl border border-border bg-surface px-3 py-3">
              {titleNotices.map((notice) => (
                <NoticeBlock key={`${notice.kind}-${notice.occurred_at}`} notice={notice} />
              ))}
            </div>
          ) : null}
          {article.summary ? <p className="article-dek mt-5">{article.summary}</p> : null}
          <div className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-2 font-sans text-[13px] text-secondary">
            {stamp ? (
              <time dateTime={article.published_at ?? undefined}>{stamp}</time>
            ) : null}
            {updated ? (
              <span>
                Actualizado <RelativeTime iso={article.updated_at} />
              </span>
            ) : null}
            {minutes ? (
              <>
                <span aria-hidden className="text-border">
                  |
                </span>
                <span>{minutes} min de lectura</span>
              </>
            ) : null}
            <span className="ml-auto flex items-center gap-3">
              <ShareButton href={href} title={article.headline} text={article.summary} />
            </span>
          </div>
        </header>
        <div className="hidden xl:block" aria-hidden="true" />

        <div className="min-w-0 max-w-[var(--article-measure)]">
          {article.hero_image_url ? (
            <PublicHero
              src={article.hero_image_url}
              className="mt-6 overflow-hidden rounded-xl"
              sizes="(min-width: 1280px) 680px, 100vw"
              priority
            />
          ) : null}

          <p className="mt-6 flex items-start gap-2 font-sans text-[13px] leading-relaxed text-secondary">
            <Info className="mt-0.5 h-4 w-4 shrink-0 text-muted" strokeWidth={1.7} aria-hidden />
            <span className="xl:hidden">Tocá las frases subrayadas para conocer su respaldo.</span>
            <span className="hidden xl:inline">Explorá las frases subrayadas para conocer su respaldo.</span>
          </p>

          <ArticleBody
            body={article.body}
            bodyBlocks={article.body_blocks}
            claims={article.claims}
            sourceKey={`${article.slug}:${article.published_version ?? ""}`}
          />

          <div className="mt-10 border-t border-border pt-5">
            <h2 className="font-sans text-[12px] font-medium uppercase tracking-[0.16em] text-muted">
              Fuentes y actualizaciones
            </h2>
            <div className="mt-3">
              <SourceList sources={article.sources} />
            </div>
          </div>

          {history.length > 0 ? (
            <div className="mt-8 border-t border-border pt-5">
              <h2 className="font-sans text-[12px] font-medium uppercase tracking-[0.16em] text-muted">Historial</h2>
              <ol className="mt-3 space-y-3">
                {history.map((item, index) => (
                  <li key={`${item.type}-${item.occurred_at}-${index}`} className="font-sans text-sm text-secondary">
                    <p className="text-primary">
                      {historyLabel(item)}
                      {item.occurred_at ? ` — ${formatNoticeStamp(item.occurred_at)}` : ""}
                    </p>
                    {item.notice ? <p className="mt-1">{item.notice}</p> : null}
                  </li>
                ))}
              </ol>
            </div>
          ) : null}

          <div className="mt-8 border-t border-border pt-5">
            <h2 className="article-kicker text-primary">¿Hay algo que debamos revisar?</h2>
            <p className="mt-2 font-sans text-sm text-secondary">
              Podés señalar un error, aportar una fuente o responder si estás involucrado.
            </p>
            {!formOpen ? (
              <button type="button" onClick={() => setFormOpen(true)} className="sl-btn mt-4">
                Reportar o consultar esta noticia
              </button>
            ) : (
              <CaseForm
                articleId={article.article_id}
                articleSlug={article.slug}
                reportedVersion={article.published_version}
                storageKey={`case-idempotency:${article.slug}:${article.published_version ?? "x"}`}
              />
            )}
          </div>
        </div>

        <aside
          data-evidence-column
          className="relative hidden min-h-[12rem] xl:block"
          aria-hidden="true"
        />
      </div>
    </article>
  );
}
