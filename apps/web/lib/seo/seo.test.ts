import assert from "node:assert/strict";
import { test } from "node:test";

import { buildArticleMetadata, notFoundArticleMetadata, articleOgImage } from "./metadata";
import { breadcrumbJsonLd, jsonLdScript, newsArticleJsonLd, organizationJsonLd, webSiteJsonLd } from "./json-ld";
import { buildRobotsRules, robotsDisallowsBuscar, sitemapAbsoluteUrl, staticSitemapUrls } from "./robots-config";
import { buildSharePayload } from "./share";
import {
  articleUrl,
  getSiteUrl,
  isIndexableDeploy,
  looksLikePublicId,
  publicSiteOrigin,
} from "./site-url";

const ORIGIN = "https://sinlinea.example";

const published = {
  slug: "colectivo-pellegrini",
  headline: "Un colectivo chocó en Pellegrini",
  summary: "Dos unidades colisionaron esta tarde.",
  hero_image_url: "/api/v1/media/heroes/11111111-1111-1111-1111-111111111111.png?v=abc",
  published_at: "2026-09-16T12:00:00+00:00",
  updated_at: "2026-09-16T15:30:00+00:00",
};

test("SITE_URL wins over preview host", () => {
  const origin = publicSiteOrigin({
    host: "proyecto-random.vercel.app",
    forwardedHost: "proyecto-random.vercel.app",
    forwardedProto: "https",
    siteUrl: ORIGIN,
  });
  assert.equal(origin, ORIGIN);
});

test("getSiteUrl falls back to localhost when unset", () => {
  assert.equal(getSiteUrl({}), "http://localhost:3000");
  assert.equal(getSiteUrl({ SITE_URL: `${ORIGIN}/` }), ORIGIN);
});

test("getSiteUrl uses VERCEL_URL when SITE_URL is unset", () => {
  assert.equal(getSiteUrl({ VERCEL_URL: "sin-linea.vercel.app" }), "https://sin-linea.vercel.app");
  assert.equal(getSiteUrl({ SITE_URL: ORIGIN, VERCEL_URL: "preview.vercel.app" }), ORIGIN);
});

test("getSiteUrl prefers production domain on Vercel production", () => {
  assert.equal(
    getSiteUrl({
      VERCEL_ENV: "production",
      VERCEL_PROJECT_PRODUCTION_URL: "sin-linea.vercel.app",
      VERCEL_URL: "sin-linea-abc123.vercel.app",
    }),
    "https://sin-linea.vercel.app",
  );
  assert.equal(
    getSiteUrl({
      VERCEL_ENV: "preview",
      VERCEL_PROJECT_PRODUCTION_URL: "sin-linea.vercel.app",
      VERCEL_URL: "sin-linea-abc123.vercel.app",
    }),
    "https://sin-linea-abc123.vercel.app",
  );
});

test("isIndexableDeploy treats missing VERCEL_ENV as indexable", () => {
  assert.equal(isIndexableDeploy({}), true);
  assert.equal(isIndexableDeploy({ VERCEL_ENV: "production" }), true);
  assert.equal(isIndexableDeploy({ VERCEL_ENV: "preview" }), false);
  assert.equal(isIndexableDeploy({ VERCEL_ENV: "development" }), false);
});

test("published article metadata uses editorial fields and absolute canonical", () => {
  const meta = buildArticleMetadata(published, ORIGIN);
  assert.equal(meta.title, published.headline);
  assert.equal(meta.description, published.summary);
  assert.equal(meta.alternates.canonical, `${ORIGIN}/noticias/${published.slug}`);
  assert.equal(meta.openGraph.type, "article");
  assert.equal(meta.openGraph.url, `${ORIGIN}/noticias/${published.slug}`);
  assert.equal(meta.openGraph.publishedTime, published.published_at);
  assert.equal(meta.openGraph.modifiedTime, published.updated_at);
  assert.equal(meta.openGraph.siteName, "Sin Línea");
  assert.equal(meta.twitter.card, "summary_large_image");
  assert.equal(meta.twitter.title, published.headline);
  assert.match(meta.openGraph.images[0].url, /\/api\/v1\/media\/heroes\//);
});

test("article without hero uses OG fallback", () => {
  const image = articleOgImage(null, ORIGIN);
  assert.equal(image.url, `${ORIGIN}/og-default.png`);
  assert.equal(image.width, 1200);
  assert.equal(image.height, 630);
  const withHero = articleOgImage(published.hero_image_url, ORIGIN);
  assert.equal(withHero.url, `${ORIGIN}${published.hero_image_url}`);
});

test("missing article metadata is noindex", () => {
  const meta = notFoundArticleMetadata();
  assert.equal(meta.robots.index, false);
  assert.equal(meta.robots.follow, false);
});

test("NewsArticle JSON-LD uses known fields only", () => {
  const data = newsArticleJsonLd(published, ORIGIN);
  assert.equal(data["@type"], "NewsArticle");
  assert.equal(data.headline, published.headline);
  assert.equal(data.datePublished, published.published_at);
  assert.equal(data.dateModified, published.updated_at);
  assert.equal(data.publisher.name, "Sin Línea");
  assert.equal(data.mainEntityOfPage["@id"], articleUrl(published.slug, ORIGIN));
  assert.equal("author" in data, false);
  assert.equal("keywords" in data, false);
  const org = organizationJsonLd(ORIGIN);
  assert.equal("logo" in org, false);
  const site = webSiteJsonLd(ORIGIN);
  assert.equal(site["@type"], "WebSite");
  const crumbs = breadcrumbJsonLd(published, ORIGIN);
  assert.equal(crumbs.itemListElement[1].item, articleUrl(published.slug, ORIGIN));
});

test("json-ld escapes < to keep the script safe", () => {
  const html = jsonLdScript({ headline: "A <script>alert(1)</script>" });
  assert.equal(html.includes("<script>"), false);
  assert.match(html, /\\u003cscript/);
});

test("robots allow buscar and point sitemap at SITE_URL", () => {
  const rules = buildRobotsRules(true);
  assert.equal(Array.isArray(rules.disallow) && robotsDisallowsBuscar(rules.disallow), false);
  assert.ok(Array.isArray(rules.disallow) && rules.disallow.includes("/admin"));
  assert.equal(sitemapAbsoluteUrl(ORIGIN), `${ORIGIN}/sitemap.xml`);
  const preview = buildRobotsRules(false);
  assert.equal(preview.disallow, "/");
  const staticUrls = staticSitemapUrls(ORIGIN).map((row) => row.url);
  assert.ok(staticUrls.includes(ORIGIN));
  assert.ok(staticUrls.includes(`${ORIGIN}/en-vivo`));
  assert.equal(staticUrls.includes(`${ORIGIN}/buscar`), false);
});

test("share payload keeps canonical article path", () => {
  const payload = buildSharePayload({
    title: published.headline,
    text: published.summary,
    path: `/noticias/${published.slug}`,
  });
  assert.equal(payload.path, `/noticias/${published.slug}`);
  assert.equal(payload.title, published.headline);
});

test("public_id is distinct from the canonical slug", () => {
  const publicId = "0ddb9aaa-85c0-4316-8771-67dafa017d86";
  assert.equal(looksLikePublicId(publicId), true);
  assert.equal(looksLikePublicId(published.slug), false);
  assert.notEqual(publicId, published.slug);
});
