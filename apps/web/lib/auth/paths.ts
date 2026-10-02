const AUTH_ENTRY = ["/entrar", "/registro"] as const;

const PRIVATE_PREFIXES = [
  "/perfil",
  "/guardados",
  "/en-vivo",
  "/local",
  "/buscar",
  "/onboarding",
  "/dev",
] as const;

export function isAuthEntryPath(pathname: string): boolean {
  return AUTH_ENTRY.some((base) => pathname === base || pathname.startsWith(`${base}/`));
}

export function isPrivateAppPath(pathname: string): boolean {
  if (pathname === "/") return true;
  return PRIVATE_PREFIXES.some((base) => pathname === base || pathname.startsWith(`${base}/`));
}
