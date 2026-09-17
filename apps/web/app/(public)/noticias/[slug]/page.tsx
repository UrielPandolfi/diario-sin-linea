import { ArticleView } from "@/features/article/article-view";
import { fetchArticle, PublicApiError } from "@/lib/api/public";
import { absolutePublicUrl, publicSiteOrigin } from "@/lib/site-url";
import type { Metadata } from "next";
import { headers } from "next/headers";
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

async function siteOrigin(): Promise<string> {
  const headerList = await headers();
  return publicSiteOrigin({
    host: headerList.get("host"),
    forwardedHost: headerList.get("x-forwarded-host"),
    forwardedProto: headerList.get("x-forwarded-proto"),
    siteUrl: process.env.SITE_URL,
  });
}

export async function generateMetadata({ params }: { params: Promise<Params> }): Promise<Metadata> {
  const { slug } = await params;
  const article = await loadArticle(slug);
  if (!article) {
    return { title: "Noticia no encontrada" };
  }
  const origin = await siteOrigin();
  const hero = absolutePublicUrl(article.hero_image_url, origin);
  return {
    metadataBase: new URL(origin),
    title: article.headline,
    description: article.summary,
    alternates: { canonical: `/noticias/${article.slug}` },
    openGraph: {
      title: article.headline,
      description: article.summary,
      type: "article",
      url: `/noticias/${article.slug}`,
      images: hero ? [{ url: hero }] : undefined,
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
