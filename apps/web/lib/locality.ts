export const LOCALITY_COOKIE = "sl_locality";
const MAX_AGE = 60 * 60 * 24 * 365;

export function readLocalityCookie(): string | null {
  if (typeof document === "undefined") return null;
  const parts = document.cookie.split("; ");
  const row = parts.find((part) => part.startsWith(`${LOCALITY_COOKIE}=`));
  if (!row) return null;
  const value = row.slice(LOCALITY_COOKIE.length + 1);
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

export function writeLocalityCookie(value: string): void {
  document.cookie = `${LOCALITY_COOKIE}=${encodeURIComponent(value)}; Path=/; Max-Age=${MAX_AGE}; SameSite=Lax`;
}

export function clearLocalityCookie(): void {
  document.cookie = `${LOCALITY_COOKIE}=; Path=/; Max-Age=0; SameSite=Lax`;
}
