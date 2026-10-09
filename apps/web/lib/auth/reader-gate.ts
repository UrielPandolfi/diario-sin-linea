import { isAuthEntryPath, isPrivateAppPath } from "@/lib/auth/paths";
import { READER_COOKIE } from "@/lib/auth/session-token";

/** Cookie firmada, sin preguntarle todavía a la API si el lector sigue existiendo. */
export type SignedReader = "missing" | "accepted" | "rejected" | "unchecked";

export type ReaderGateAction = "pass" | "show-login" | "show-app" | "clear-login" | "clear-stay" | "clear-pass";

export function signedReaderState(hasValidCookie: boolean, apiAuthenticated: boolean | null): SignedReader {
  if (!hasValidCookie) return "missing";
  if (apiAuthenticated === true) return "accepted";
  if (apiAuthenticated === false) return "rejected";
  return "unchecked";
}

export function readerGateAction(pathname: string, state: SignedReader): ReaderGateAction {
  if (state === "rejected") {
    if (isAuthEntryPath(pathname)) return "clear-stay";
    if (isPrivateAppPath(pathname)) return "clear-login";
    return "clear-pass";
  }
  const authenticated = state === "accepted" || state === "unchecked";
  if (isAuthEntryPath(pathname) && authenticated) return "show-app";
  if (isPrivateAppPath(pathname) && !authenticated) return "show-login";
  return "pass";
}

/** Dos bajas: una con Secure y otra sin, para coincidir con como se guardó la cookie. */
export function readerCookieExpiry(): [string, string] {
  const base = `${READER_COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax`;
  return [base, `${base}; Secure`];
}
