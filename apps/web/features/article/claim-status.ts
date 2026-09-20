import type { ArticleClaim } from "../../lib/api/types";

const EDITORIAL_LABELS: Record<string, string> = {
  CHECKED: "Chequeado",
  DISCREPANCY: "Discrepancia",
  DISPUTED: "En disputa",
  FALSE_CLAIM: "Afirmación falsa",
};

export function editorialLabelCopy(label: string): string {
  return EDITORIAL_LABELS[label] ?? label;
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
