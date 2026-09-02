import type { ArticleClaim } from "@/lib/api/types";

const STATUS_LABELS: Record<string, string> = {
  SUPPORTED: "Confirmado",
  SINGLE_SOURCE: "Una fuente",
  CONFLICTING: "En conflicto",
  UNCERTAIN: "Incierto",
  DISPROVEN: "Desmentido",
  OUTDATED: "Desactualizado",
};

export function claimStatusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status;
}

export function claimsForIds(ids: string[], claims: ArticleClaim[] | undefined): ArticleClaim[] {
  if (!ids.length || !claims?.length) return [];
  const byId = new Map(claims.map((claim) => [claim.id, claim]));
  const seen = new Set<string>();
  const rows: ArticleClaim[] = [];
  for (const id of ids) {
    if (seen.has(id)) continue;
    seen.add(id);
    const claim = byId.get(id);
    if (claim) rows.push(claim);
  }
  return rows;
}
