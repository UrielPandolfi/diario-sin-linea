import { isAuthEntryPath } from "@/lib/auth/paths";

const INTERNAL_ORIGIN = "http://sinlinea.internal";

export function safeReturnTo(value: string | null | undefined, fallback = "/"): string {
  if (!value || value !== value.trim()) return fallback;
  const trimmed = value;
  if (!trimmed.startsWith("/") || trimmed.startsWith("//") || trimmed.startsWith("/\\")) return fallback;
  if (/[\s\\]/.test(trimmed) || trimmed.includes("://") || trimmed.includes("\0")) return fallback;
  let url: URL;
  try {
    url = new URL(trimmed, INTERNAL_ORIGIN);
  } catch {
    return fallback;
  }
  if (url.origin !== INTERNAL_ORIGIN || url.username || url.password) return fallback;
  const path = `${url.pathname}${url.search}${url.hash}`;
  if (!path.startsWith("/") || path.startsWith("//") || isAuthEntryPath(url.pathname)) return fallback;
  return path;
}

export function loginPath(next: string | null | undefined, fallback = "/"): string {
  return `/entrar?next=${encodeURIComponent(safeReturnTo(next, fallback))}`;
}

export function registerPath(next: string | null | undefined, fallback = "/"): string {
  return `/registro?next=${encodeURIComponent(safeReturnTo(next, fallback))}`;
}
