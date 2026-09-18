import { buildRobotsRules, sitemapAbsoluteUrl } from "@/lib/seo/robots-config";
import { getSiteUrl, isIndexableDeploy } from "@/lib/seo/site-url";
import type { MetadataRoute } from "next";

export default function robots(): MetadataRoute.Robots {
  const origin = getSiteUrl();
  return {
    rules: buildRobotsRules(isIndexableDeploy()),
    sitemap: sitemapAbsoluteUrl(origin),
  };
}
