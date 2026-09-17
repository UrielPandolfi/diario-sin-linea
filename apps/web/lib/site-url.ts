export function publicSiteOrigin(input: {
  host?: string | null;
  forwardedHost?: string | null;
  forwardedProto?: string | null;
  siteUrl?: string | null;
}): string {
  const host = (input.forwardedHost || input.host || "").split(",")[0]?.trim();
  if (host) {
    const forwarded = (input.forwardedProto || "").split(",")[0]?.trim();
    const local = host.startsWith("localhost") || host.startsWith("127.0.0.1");
    const proto = forwarded || (local ? "http" : "https");
    return `${proto}://${host}`;
  }
  const fallback = (input.siteUrl || "").trim().replace(/\/$/, "");
  if (fallback) {
    return fallback;
  }
  return "http://localhost:3000";
}

export function absolutePublicUrl(pathOrUrl: string | null | undefined, origin: string): string | undefined {
  if (!pathOrUrl) {
    return undefined;
  }
  if (pathOrUrl.startsWith("http://") || pathOrUrl.startsWith("https://")) {
    return pathOrUrl;
  }
  const path = pathOrUrl.startsWith("/") ? pathOrUrl : `/${pathOrUrl}`;
  return `${origin}${path}`;
}
