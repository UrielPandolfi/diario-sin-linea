import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const LOCALITY_COOKIE = "sl_locality";

const OPEN_WITHOUT_LOCALITY = [
  /^\/entrar\/?$/,
  /^\/onboarding\/?$/,
  /^\/como-funciona\/?$/,
  /^\/contacto\/?$/,
  /^\/seguimiento(\/|$)/,
  /^\/noticias(\/|$)/,
  /^\/admin(\/|$)/,
  /^\/api(\/|$)/,
];

function isOpen(pathname: string): boolean {
  return OPEN_WITHOUT_LOCALITY.some((pattern) => pattern.test(pathname));
}

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const locality = request.cookies.get(LOCALITY_COOKIE)?.value;

  if (pathname === "/entrar" && locality) {
    return NextResponse.redirect(new URL("/", request.url));
  }

  if (!isOpen(pathname) && !locality) {
    return NextResponse.redirect(new URL("/entrar", request.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|mark.svg|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)$).*)"],
};
