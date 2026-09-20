import type { ArticleClaim, ClaimEvidenceDetail } from "@/lib/api/types";

const OFFICIAL_LIMITATION_MARKERS = [
  "El documento oficial no sostiene esta proposición.",
  "El documento oficial consultado no sostiene esta proposición.",
];

export function claimPopoverCopy(claim: ArticleClaim) {
  const card = claim.presentation;
  const heading = card?.verification_label ?? "Sin evaluación disponible";
  const explanation = card?.explanation ?? null;
  const limitation = card?.limitation ?? null;
  const documentaryLimitation = limitation && OFFICIAL_LIMITATION_MARKERS.includes(limitation) ? limitation : null;

  return {
    heading,
    explanation,
    limitation: documentaryLimitation ? null : limitation,
    coverage: card?.coverage ?? null,
    documentaryLimitation,
  };
}

export function officialDocumentDetailIndex(details: ClaimEvidenceDetail[]): number {
  const candidates = details.flatMap((row, index) => {
    if (!row.url || row.evidence_type === "SUPPORTS") return [];
    try {
      const host = new URL(row.url).hostname;
      return /\.(?:gob|gov)\.[a-z]{2}$|\.gov$/i.test(host) ? [index] : [];
    } catch {
      return [];
    }
  });
  return candidates.length === 1 ? candidates[0] : -1;
}
