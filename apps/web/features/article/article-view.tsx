"use client";

import { ArticleBody } from "@/features/article/article-body";
import { ShareButton } from "@/features/article/share-button";
import { SourceList } from "@/features/feed/source-list";
import { RelativeTime } from "@/components/relative-time";
import type { Article } from "@/lib/api/types";
import { formatDateTime, isMateriallyUpdated } from "@/lib/relative-time";
import Image from "next/image";

export function ArticleView({ article }: { article: Article }) {
  const href = `/noticias/${article.slug}`;
  const updated = isMateriallyUpdated(article.published_at, article.updated_at);

  return (
    <article className="mx-auto max-w-[42rem] px-4 py-8 md:px-6">
      <p className="font-sans text-[11px] uppercase tracking-[0.14em] text-muted">
        {article.locality}
        {article.locality && article.published_at ? " · " : null}
        {article.published_at ? formatDateTime(article.published_at) : null}
      </p>
      <h1 className="mt-3 font-heading text-3xl font-medium leading-tight text-primary">{article.headline}</h1>
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

      <p className="mt-6 font-sans text-sm text-muted">Discrepancias · Próximamente</p>
      <p className="mt-1 font-sans text-sm text-muted">Actualizaciones del suceso · Próximamente</p>

      <div className="mt-6">
        <ShareButton href={href} />
      </div>
    </article>
  );
}
