import {
  DEFAULT_OG_IMAGE_PATH,
  OG_IMAGE_HEIGHT,
  OG_IMAGE_WIDTH,
  OG_LOCALE,
  SITE_DESCRIPTION,
  SITE_NAME,
} from "./constants";
import { absolutePublicUrl, articleUrl } from "./site-url";

export type ArticleSeoInput = {
  slug: string;
  headline: string;
  summary: string;
  hero_image_url: string | null;
  published_at: string | null;
  updated_at: string | null;
};

export type SeoImage = {
  url: string;
  width: number;
  height: number;
};

export const NO_INDEX_NO_FOLLOW = { index: false, follow: false } as const;
export const NO_INDEX_FOLLOW = { index: false, follow: true } as const;

export function defaultOgImage(origin: string): SeoImage {
  return {
    url: `${origin}${DEFAULT_OG_IMAGE_PATH}`,
    width: OG_IMAGE_WIDTH,
    height: OG_IMAGE_HEIGHT,
  };
}

export function articleOgImage(heroImageUrl: string | null | undefined, origin: string): SeoImage {
  const hero = absolutePublicUrl(heroImageUrl, origin);
  if (hero) {
    return { url: hero, width: OG_IMAGE_WIDTH, height: OG_IMAGE_HEIGHT };
  }
  return defaultOgImage(origin);
}

export function modifiedTime(article: ArticleSeoInput): string | undefined {
  return article.updated_at || article.published_at || undefined;
}

export function buildArticleMetadata(article: ArticleSeoInput, origin: string) {
  const canonical = articleUrl(article.slug, origin);
  const image = articleOgImage(article.hero_image_url, origin);
  const published = article.published_at ?? undefined;
  const modified = modifiedTime(article);
  return {
    title: article.headline,
    description: article.summary,
    alternates: { canonical },
    openGraph: {
      title: article.headline,
      description: article.summary,
      type: "article" as const,
      url: canonical,
      siteName: SITE_NAME,
      locale: OG_LOCALE,
      publishedTime: published,
      modifiedTime: modified,
      images: [image],
    },
    twitter: {
      card: "summary_large_image" as const,
      title: article.headline,
      description: article.summary,
      images: [image.url],
    },
  };
}

export function notFoundArticleMetadata() {
  return {
    title: "Noticia no encontrada",
    robots: NO_INDEX_NO_FOLLOW,
  };
}

export function rootMetadata(origin: string, indexable: boolean) {
  return {
    metadataBase: new URL(origin),
    title: {
      default: SITE_NAME,
      template: "%s · Sin Línea",
    },
    description: SITE_DESCRIPTION,
    applicationName: SITE_NAME,
    icons: { icon: "/mark.svg" },
    robots: indexable ? { index: true, follow: true } : NO_INDEX_NO_FOLLOW,
    openGraph: {
      type: "website" as const,
      locale: OG_LOCALE,
      siteName: SITE_NAME,
      title: SITE_NAME,
      description: SITE_DESCRIPTION,
    },
    twitter: {
      card: "summary_large_image" as const,
      title: SITE_NAME,
      description: SITE_DESCRIPTION,
    },
  };
}

export { SITE_DESCRIPTION, SITE_NAME };
