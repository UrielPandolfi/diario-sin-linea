"use client";

import { ArticleBody } from "@/features/article/article-body";
import { ShareButton } from "@/features/article/share-button";
import { CaseForm } from "@/features/cases/case-form";
import { SourceList } from "@/features/feed/source-list";
import { RelativeTime } from "@/components/relative-time";
import type { Article, ArticleHistoryItem, ArticleNotice } from "@/lib/api/types";
import { formatDateTime, isMateriallyUpdated } from "@/lib/relative-time";
import Image from "next/image";
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

export function ArticleView({ article }: { article: Article }) {
  const href = `/noticias/${article.slug}`;
  const updated = isMateriallyUpdated(article.published_at, article.updated_at);
  const [formOpen, setFormOpen] = useState(false);
  const titleNotices = (article.notices ?? []).filter((item) => item.show_near_title);
  const history = article.history ?? [];

  return (
    <article className="mx-auto max-w-[42rem] px-4 py-8 md:px-6">
      <p className="font-sans text-[11px] uppercase tracking-[0.14em] text-muted">
        {article.locality}
        {article.locality && article.published_at ? " · " : null}
        {article.published_at ? formatDateTime(article.published_at) : null}
      </p>
      <h1 className="mt-3 font-heading text-3xl font-medium leading-tight text-primary">{article.headline}</h1>
      {titleNotices.length > 0 ? (
        <div className="mt-4 space-y-2 border border-border bg-surface px-3 py-3">
          {titleNotices.map((notice) => (
            <NoticeBlock key={`${notice.kind}-${notice.occurred_at}`} notice={notice} />
          ))}
        </div>
      ) : null}
      {article.summary ? (
        <p className="mt-4 font-sans text-base leading-relaxed text-secondary">{article.summary}</p>
      ) : null}
      {updated ? (
        <p className="mt-3 font-sans text-xs text-muted">
          Actualizado <RelativeTime iso={article.updated_at} />
        </p>
      ) : null}

      {article.hero_image_url ? (
        <div className="relative mt-6 aspect-[16/9] overflow-hidden bg-surface">
          <Image
            src={article.hero_image_url}
            alt=""
            fill
            className="object-cover"
            sizes="(min-width: 768px) 672px, 100vw"
            priority
            unoptimized
          />
        </div>
      ) : null}

      <ArticleBody body={article.body} bodyBlocks={article.body_blocks} claims={article.claims} />

      <div className="mt-8 border-t border-border pt-5">
        <h2 className="font-heading text-xs uppercase tracking-[0.16em] text-muted">Fuentes</h2>
        <div className="mt-2">
          <SourceList sources={article.sources} />
        </div>
      </div>

      {history.length > 0 ? (
        <div className="mt-8 border-t border-border pt-5">
          <h2 className="font-heading text-xs uppercase tracking-[0.16em] text-muted">Historial</h2>
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

      <p className="mt-6 font-sans text-sm text-muted">Discrepancias · Próximamente</p>

      <div className="mt-8 border-t border-border pt-5">
        <h2 className="font-heading text-lg text-primary">¿Hay algo que debamos revisar?</h2>
        <p className="mt-2 font-sans text-sm text-secondary">
          Podés señalar un error, aportar una fuente o responder si estás involucrado.
        </p>
        {!formOpen ? (
          <button
            type="button"
            onClick={() => setFormOpen(true)}
            className="mt-4 border border-border bg-hover px-3 py-2 font-sans text-sm text-primary"
          >
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

      <div className="mt-6">
        <ShareButton href={href} />
      </div>
    </article>
  );
}