export const LIVE_POLL_MS = 45_000;
export const NEW_LABEL_MS = 8_000;
export const FRESH_MS = 5 * 60 * 1000;

const liveClock = new Intl.DateTimeFormat("es-AR", {
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});

export function formatLiveClock(now: number): string {
  return liveClock.format(now);
}

export function formatUpdatedAgo(updatedAt: number, now: number): string {
  const seconds = Math.max(0, Math.floor((now - updatedAt) / 1000));
  if (seconds < 1) return "Actualizado ahora";
  if (seconds < 60) return `Actualizado hace ${seconds} s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `Actualizado hace ${minutes} min`;
  const hours = Math.floor(minutes / 60);
  return `Actualizado hace ${hours} h`;
}

export function isFresh(iso: string | null, now: number, windowMs = FRESH_MS): boolean {
  if (!iso || now <= 0) return false;
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return false;
  const age = now - then;
  return age >= 0 && age < windowMs;
}

export function isNewArrival(arrivedAt: number | undefined, now: number): boolean {
  if (arrivedAt == null || now <= 0) return false;
  const age = now - arrivedAt;
  return age >= 0 && age < NEW_LABEL_MS;
}

/** Ids that entered at the top since the previous snapshot. The first snapshot is a baseline. */
export function prefixArrivals(previous: readonly string[] | null, next: readonly string[]): string[] {
  if (previous === null) return [];
  const seen = new Set(previous);
  const fresh: string[] = [];
  for (const key of next) {
    if (seen.has(key)) break;
    fresh.push(key);
  }
  return fresh;
}
