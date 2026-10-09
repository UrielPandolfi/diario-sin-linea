import { isAuthEntryPath, isPrivateAppPath } from "@/lib/auth/paths";
import { readerCookieExpiry, readerGateAction, signedReaderState } from "@/lib/auth/reader-gate";
import { safeReturnTo } from "@/lib/auth/return-to";
import { readerSessionSecret } from "@/lib/auth/secret";
import { READER_COOKIE, verifyReaderToken } from "@/lib/auth/session-token";
import { isIndexableDeploy } from "@/lib/seo/site-url";
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

async function readerStillExists(request: NextRequest): Promise<boolean | null> {
  const api = process.env.API_URL || "http://localhost:8000";
  try {
    const response = await fetch(`${api}/api/v1/auth/session`, {
      headers: { cookie: request.headers.get("cookie") ?? "" },
      cache: "no-store",
      signal: AbortSignal.timeout(4000),
    });
    if (!response.ok) return null;
    const body = (await response.json()) as { authenticated?: unknown };
    return typeof body.authenticated === "boolean" ? body.authenticated : null;
  } catch {
    return null;
  }
}

async function adminSession(request: NextRequest): Promise<boolean> {
  const api = process.env.API_URL || "http://localhost:8000";
  try {
    const response = await fetch(`${api}/api/v1/admin/me`, {
      headers: { cookie: request.headers.get("cookie") ?? "" },
      cache: "no-store",
    });
    return response.ok;
  } catch {
    return false;
  }
}

export async function middleware(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  if ((pathname === "/admin" || pathname.startsWith("/admin/")) && pathname !== "/admin/login") {
    if (!(await adminSession(request))) {
      return NextResponse.redirect(new URL("/admin/login", request.url));
    }
  }
  if (process.env.NODE_ENV === "production" && (pathname === "/dev" || pathname.startsWith("/dev/"))) {
    return NextResponse.next();
  }
  const reader = await verifyReaderToken(request.cookies.get(READER_COOKIE)?.value, readerSessionSecret());
  let state = signedReaderState(reader !== null, null);
  if (reader !== null && (isAuthEntryPath(pathname) || isPrivateAppPath(pathname))) {
    state = signedReaderState(true, await readerStillExists(request));
  }
  const action = readerGateAction(pathname, state);

  let response: NextResponse;
  if (action === "show-app") {
    response = NextResponse.redirect(new URL(safeReturnTo(request.nextUrl.searchParams.get("next"), "/"), request.url));
  } else if (action === "show-login" || action === "clear-login") {
    const login = new URL("/entrar", request.url);
    login.searchParams.set("next", safeReturnTo(`${pathname}${search}`, "/"));
    response = NextResponse.redirect(login);
  } else if (action === "clear-stay") {
    response = NextResponse.redirect(request.nextUrl);
  } else {
    response = NextResponse.next();
  }
  if (action === "clear-login" || action === "clear-stay" || action === "clear-pass") {
    for (const cookie of readerCookieExpiry()) response.headers.append("Set-Cookie", cookie);
  }

  if (!pathname.startsWith("/api/")) {
    response.headers.set("Cache-Control", "private, no-store");
  }
  if (pathname === "/transparencia" || pathname.startsWith("/transparencia/")) {
    response.headers.set("X-Robots-Tag", "noindex, nofollow");
    response.headers.set("Cache-Control", "private, no-store");
  } else if (!isIndexableDeploy()) {
    response.headers.set("X-Robots-Tag", "noindex, nofollow");
  }
  return response;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|mark.svg|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)$).*)"],
};
