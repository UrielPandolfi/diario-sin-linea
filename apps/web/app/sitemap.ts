import { fetchSitemapArticles } from "@/lib/api/public";
import { staticSitemapUrls } from "@/lib/seo/robots-config";
import { articleUrl, getSiteUrl } from "@/lib/seo/site-url";
import type { MetadataRoute } from "next";

export const dynamic = "force-dynamic";

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const origin = getSiteUrl();
  const entries: MetadataRoute.Sitemap = staticSitemapUrls(origin);
  try {
    const payload = await fetchSitemapArticles();
    for (const item of payload.items) {
      entries.push({
        url: articleUrl(item.slug, origin),
        lastModified: item.updated_at || item.published_at || undefined,
      });
    }
  } catch {
    return entries;
  }
  return entries;
}
