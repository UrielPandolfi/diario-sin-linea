export type ReadingSize = "sm" | "md" | "lg";

export const READING_SIZE_KEY = "sl-reading-size";
export const READING_SIZES: ReadingSize[] = ["sm", "md", "lg"];

export function parseReadingSize(value: string | null | undefined): ReadingSize | null {
  return value === "sm" || value === "md" || value === "lg" ? value : null;
}

export function resolveReadingSize(value: string | null | undefined): ReadingSize {
  return parseReadingSize(value) ?? "md";
}

export function readingMinutes(parts: Array<string | null | undefined>): number | null {
  const text = parts.filter(Boolean).join(" ").replace(/\s+/g, " ").trim();
  if (!text) return null;
  const words = text.split(" ").filter(Boolean).length;
  if (words === 0) return null;
  return Math.max(1, Math.round(words / 230));
}

export function formatArticleStamp(iso: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const day = new Intl.DateTimeFormat("es-AR", { day: "numeric" }).format(date);
  const month = new Intl.DateTimeFormat("es-AR", { month: "short" }).format(date).replace(".", "");
  const year = new Intl.DateTimeFormat("es-AR", { year: "numeric" }).format(date);
  const time = new Intl.DateTimeFormat("es-AR", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
  return `${day} ${month} ${year} · ${time}`;
}
