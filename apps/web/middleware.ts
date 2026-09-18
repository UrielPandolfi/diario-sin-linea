import { isIndexableDeploy } from "@/lib/seo/site-url";
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const LOCALITY_COOKIE = "sl_locality";

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const locality = request.cookies.get(LOCALITY_COOKIE)?.value;

  const response =
    pathname === "/entrar" && locality
      ? NextResponse.redirect(new URL("/", request.url))
      : NextResponse.next();

  if (!isIndexableDeploy()) {
    response.headers.set("X-Robots-Tag", "noindex, nofollow");
  }

  return response;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|mark.svg|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)$).*)"],
};
