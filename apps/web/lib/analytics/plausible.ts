export const PLAUSIBLE_SCRIPT_SRC = "https://plausible.io/js/pa-6mqOMwf_auvTj84k5bSp_.js";

const PLAUSIBLE_INIT_STUB =
  "window.plausible=window.plausible||function(){(plausible.q=plausible.q||[]).push(arguments)},plausible.init=plausible.init||function(i){plausible.o=i||{}};";

/**
 * Misma función que corre en el navegador. Solo pageviews, sin query,
 * sin propiedades y sin el token de /seguimiento. /admin no se envía.
 */
export const PLAUSIBLE_TRANSFORM_SOURCE = `function(payload) {
  if (!payload || payload.n !== "pageview" || typeof payload.u !== "string") return null;
  function clean(url) {
    var parsed;
    try {
      parsed = new URL(url);
    } catch (error) {
      return null;
    }
    var host = parsed.hostname.toLowerCase();
    var ours = host === "sinlinea.ar" || host === "www.sinlinea.ar";
    var path = parsed.pathname || "/";
    var folded = path.toLowerCase();
    if (ours && (folded === "/admin" || folded.indexOf("/admin/") === 0)) return { drop: true };
    if (ours && (folded === "/seguimiento" || folded.indexOf("/seguimiento/") === 0)) {
      return { url: parsed.origin + "/seguimiento" };
    }
    return { url: parsed.origin + path, external: !ours };
  }
  var page = clean(payload.u);
  if (!page || page.drop || page.external || !page.url) return null;
  var next = { n: "pageview", u: page.url };
  if (typeof payload.d === "string") next.d = payload.d;
  if (typeof payload.i === "boolean") next.i = payload.i;
  if (typeof payload.r === "string" && payload.r) {
    var ref = clean(payload.r);
    next.r = !ref || ref.drop ? null : ref.url;
  } else if (payload.r === null) {
    next.r = null;
  }
  return next;
}`;

export function requestHostname(value: string | null | undefined): string {
  const first = (value ?? "").split(",")[0]?.trim().toLowerCase() ?? "";
  if (!first) return "";
  if (first.startsWith("[")) {
    const end = first.indexOf("]");
    return end > 1 ? first.slice(1, end) : "";
  }
  const colon = first.lastIndexOf(":");
  if (colon > -1 && /^\d+$/.test(first.slice(colon + 1))) return first.slice(0, colon);
  return first;
}

export function isPlausibleHost(host: string | null | undefined): boolean {
  const hostname = requestHostname(host);
  return hostname === "sinlinea.ar" || hostname === "www.sinlinea.ar";
}

export function isPlausibleEnabled(
  env: Record<string, string | undefined>,
  host: string | null | undefined,
): boolean {
  return env.NODE_ENV === "production" && env.VERCEL_ENV === "production" && isPlausibleHost(host);
}

export function plausibleInitSnippet(): string {
  return `${PLAUSIBLE_INIT_STUB}plausible.init({captureOnLocalhost:false,transformRequest:${PLAUSIBLE_TRANSFORM_SOURCE}});`;
}
