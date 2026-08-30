import { ArticleView } from "@/features/article/article-view";
import { fetchArticle, PublicApiError } from "@/lib/api/public";
import type { Metadata } from "next";
import { notFound } from "next/navigation";

export const dynamic = "force-dynamic";

type Params = { slug: string };

async function loadArticle(slug: string) {
  try {
    return await fetchArticle(slug);
  } catch (error) {
    if (error instanceof PublicApiError && error.status === 404) return null;
    throw error;
  }
}

export async function generateMetadata({ params }: { params: Promise<Params> }): Promise<Metadata> {
  const { slug } = await params;
  const article = await loadArticle(slug);
  if (!article) {
    return { title: "Noticia no encontrada" };
  }
  return {
    title: article.headline,
    description: article.summary,
    alternates: { canonical: `/noticias/${article.slug}` },
    openGraph: {
      title: article.headline,
      description: article.summary,
      type: "article",
      url: `/noticias/${article.slug}`,
      images: article.hero_image_url ? [{ url: article.hero_image_url }] : undefined,
    },
  };
}

export default async function ArticlePage({ params }: { params: Promise<Params> }) {
  const { slug } = await params;
  const article = await loadArticle(slug);
  if (!article) notFound();

  return (
    <div className="min-h-screen border-x border-border">
      <ArticleView article={article} />
    </div>
  );
}
