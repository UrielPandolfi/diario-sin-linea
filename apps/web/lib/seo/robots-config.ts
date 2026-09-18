import { ROBOTS_DISALLOW, SITEMAP_STATIC_PATHS } from "./constants";

export function buildRobotsRules(indexable: boolean) {
  if (!indexable) {
    return { userAgent: "*", disallow: "/" };
  }
  return {
    userAgent: "*",
    allow: "/",
    disallow: [...ROBOTS_DISALLOW],
  };
}

export function sitemapAbsoluteUrl(origin: string): string {
  return `${origin}/sitemap.xml`;
}

export function staticSitemapUrls(origin: string): { url: string }[] {
  return SITEMAP_STATIC_PATHS.map((path) => ({
    url: path === "/" ? origin : `${origin}${path}`,
  }));
}

export function robotsDisallowsBuscar(disallow: string[]): boolean {
  return disallow.some((rule) => rule === "/buscar" || rule.startsWith("/buscar/"));
}
