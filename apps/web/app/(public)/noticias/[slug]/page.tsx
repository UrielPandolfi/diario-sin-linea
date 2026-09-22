import { ArticleView } from "@/features/article/article-view";
import { fetchArticle, PublicApiError } from "@/lib/api/public";
import type { Article } from "@/lib/api/types";
import { breadcrumbJsonLd, newsArticleJsonLd } from "@/lib/seo/json-ld";
import { JsonLd } from "@/lib/seo/json-ld-script";
import { buildArticleMetadata, notFoundArticleMetadata } from "@/lib/seo/metadata";
import { getSiteUrl } from "@/lib/seo/site-url";
import type { Metadata } from "next";
import { notFound, permanentRedirect } from "next/navigation";
import { cache } from "react";

export const dynamic = "force-dynamic";

type Params = { slug: string };

const loadArticle = cache(async (slug: string): Promise<Article | null> => {
  try {
    return await fetchArticle(slug);
  } catch (error) {
    if (error instanceof PublicApiError && (error.status === 404 || error.status === 503)) return null;
    throw error;
  }
});

export async function generateMetadata({ params }: { params: Promise<Params> }): Promise<Metadata> {
  const { slug } = await params;
  const article = await loadArticle(slug);
  if (!article) return notFoundArticleMetadata();
  return buildArticleMetadata(article, getSiteUrl());
}

export default async function ArticlePage({ params }: { params: Promise<Params> }) {
  const { slug } = await params;
  const article = await loadArticle(slug);
  if (!article) notFound();
  if (slug !== article.slug) {
    permanentRedirect(`/noticias/${article.slug}`);
  }

  const origin = getSiteUrl();
  return (
    <div className="min-h-screen">
      <JsonLd data={newsArticleJsonLd(article, origin)} />
      <JsonLd data={breadcrumbJsonLd(article, origin)} />
      <ArticleView article={article} />
    </div>
  );
}
