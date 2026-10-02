import { isAuthEntryPath, isPrivateAppPath } from "@/lib/auth/paths";
import { safeReturnTo } from "@/lib/auth/return-to";
import { readerSessionSecret } from "@/lib/auth/secret";
import { READER_COOKIE, verifyReaderToken } from "@/lib/auth/session-token";
import { isIndexableDeploy } from "@/lib/seo/site-url";
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

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
  const authenticated = reader !== null;

  let response: NextResponse;
  if (isAuthEntryPath(pathname) && authenticated) {
    response = NextResponse.redirect(new URL(safeReturnTo(request.nextUrl.searchParams.get("next"), "/"), request.url));
  } else if (isPrivateAppPath(pathname) && !authenticated) {
    const login = new URL("/entrar", request.url);
    login.searchParams.set("next", safeReturnTo(`${pathname}${search}`, "/"));
    response = NextResponse.redirect(login);
  } else {
    response = NextResponse.next();
  }

  if (!pathname.startsWith("/api/")) {
    response.headers.set("Cache-Control", "private, no-store");
  }
  if (!isIndexableDeploy()) {
    response.headers.set("X-Robots-Tag", "noindex, nofollow");
  }
  return response;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|mark.svg|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)$).*)"],
};
