import { SITE_NAME } from "./constants";
import { articleOgImage, modifiedTime, type ArticleSeoInput } from "./metadata";
import { articleUrl } from "./site-url";

export function jsonLdScript(data: unknown): string {
  return JSON.stringify(data).replace(/</g, "\\u003c");
}

export function organizationJsonLd(origin: string) {
  return {
    "@context": "https://schema.org",
    "@type": "Organization",
    name: SITE_NAME,
    url: origin,
  };
}

export function webSiteJsonLd(origin: string) {
  return {
    "@context": "https://schema.org",
    "@type": "WebSite",
    name: SITE_NAME,
    url: origin,
    inLanguage: "es-AR",
    publisher: {
      "@type": "Organization",
      name: SITE_NAME,
      url: origin,
    },
  };
}

export function newsArticleJsonLd(article: ArticleSeoInput, origin: string) {
  const canonical = articleUrl(article.slug, origin);
  const image = articleOgImage(article.hero_image_url, origin);
  const published = article.published_at ?? undefined;
  const modified = modifiedTime(article);
  return {
    "@context": "https://schema.org",
    "@type": "NewsArticle",
    headline: article.headline,
    description: article.summary,
    datePublished: published,
    dateModified: modified,
    mainEntityOfPage: {
      "@type": "WebPage",
      "@id": canonical,
    },
    image: [image.url],
    publisher: {
      "@type": "Organization",
      name: SITE_NAME,
      url: origin,
    },
  };
}

export function breadcrumbJsonLd(article: ArticleSeoInput, origin: string) {
  return {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: [
      {
        "@type": "ListItem",
        position: 1,
        name: SITE_NAME,
        item: origin,
      },
      {
        "@type": "ListItem",
        position: 2,
        name: article.headline,
        item: articleUrl(article.slug, origin),
      },
    ],
  };
}
