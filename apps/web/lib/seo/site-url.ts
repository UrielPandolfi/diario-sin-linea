import { FALLBACK_SITE_URL } from "./constants";

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function normalizeOrigin(value: string): string {
  return value.trim().replace(/\/$/, "");
}

export function getConfiguredSiteUrl(siteUrl?: string | null): string | null {
  const value = normalizeOrigin(siteUrl ?? "");
  if (!value) return null;
  try {
    const parsed = new URL(value);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return null;
    return parsed.origin;
  } catch {
    return null;
  }
}

export function publicSiteOrigin(input: {
  host?: string | null;
  forwardedHost?: string | null;
  forwardedProto?: string | null;
  siteUrl?: string | null;
}): string {
  const configured = getConfiguredSiteUrl(input.siteUrl);
  if (configured) return configured;

  const host = (input.forwardedHost || input.host || "").split(",")[0]?.trim();
  if (host) {
    const forwarded = (input.forwardedProto || "").split(",")[0]?.trim();
    const local = host.startsWith("localhost") || host.startsWith("127.0.0.1");
    const proto = forwarded || (local ? "http" : "https");
    return `${proto}://${host}`;
  }

  return FALLBACK_SITE_URL;
}

export function getSiteUrl(env: Record<string, string | undefined> = process.env): string {
  return publicSiteOrigin({ siteUrl: env.SITE_URL });
}

export function isIndexableDeploy(env: Record<string, string | undefined> = process.env): boolean {
  const vercelEnv = env.VERCEL_ENV;
  if (!vercelEnv) return true;
  return vercelEnv === "production";
}

export function absolutePublicUrl(pathOrUrl: string | null | undefined, origin: string): string | undefined {
  if (!pathOrUrl) return undefined;
  if (pathOrUrl.startsWith("http://") || pathOrUrl.startsWith("https://")) return pathOrUrl;
  const path = pathOrUrl.startsWith("/") ? pathOrUrl : `/${pathOrUrl}`;
  return `${origin}${path}`;
}

export function articlePath(slug: string): string {
  return `/noticias/${slug}`;
}

export function articleUrl(slug: string, origin: string): string {
  return `${origin}${articlePath(slug)}`;
}

export function looksLikePublicId(value: string): boolean {
  return UUID_RE.test(value);
}
