import type { ArticleClaim, ClaimEvidenceDetail } from "@/lib/api/types";

const OFFICIAL_LIMITATION = "El documento oficial no sostiene esta proposición.";
const DOCUMENT_DETAIL_LIMITATION = "El documento oficial consultado no respalda este dato específico.";
const AUTHENTIC_PRIMARY_LABEL = "Declaración documentada en la publicación original";

function publicationName(row: ClaimEvidenceDetail | undefined): string | null {
  const name = row?.name?.trim();
  if (!name) return null;
  return name.toLowerCase() === "infobae.com" ? "Infobae" : name;
}

export function claimPopoverCopy(claim: ArticleClaim) {
  const card = claim.presentation;
  let heading = card?.verification_label ?? "Independencia desconocida";
  let coverage = card?.coverage ?? "No hay desglose de independencia para esta verificación.";
  let limitation = card?.limitation ?? null;
  let explanation = card?.explanation ?? null;
  const documentaryLimitation = limitation === OFFICIAL_LIMITATION ? DOCUMENT_DETAIL_LIMITATION : null;
  if (documentaryLimitation) limitation = null;

  const reporting = card?.documents_reporting;
  const consulted = card?.documents_consulted;
  const reportableStatus = claim.status === "SINGLE_SOURCE" || claim.status === "SUPPORTED";
  // Use the recorded verification basis, never source_count or the number of links.
  if (card?.basis_known && reportableStatus) {
    const independent = claim.status === "SUPPORTED" && (card.known_independent_count ?? 0) >= 2;
    const authenticPrimary = card.verification_label === AUTHENTIC_PRIMARY_LABEL;
    if (independent) {
      heading = "Corroborado por fuentes independientes";
    } else if (!authenticPrimary && reporting != null && reporting > 0) {
      heading = reporting === 1 ? "Reportado en 1 publicación" : `Coincidencia entre ${reporting} publicaciones`;
    }

    if (reporting != null && reporting > 0 && consulted != null && consulted >= reporting) {
      const reviewed = consulted === 1 ? "el documento revisado" : `los ${consulted} documentos revisados`;
      if (reporting === 1) {
        const supporting = card.evidence_detail.filter((row) => row.evidence_type === "SUPPORTS");
        const name = supporting.length === 1 ? publicationName(supporting[0]) : null;
        const attribution = name ? `${name} reporta esta afirmación. ` : "";
        coverage = consulted === 1
          ? `${attribution}El único documento revisado respalda esta afirmación completa.`
          : name
            ? `${attribution}Es la única publicación que la respalda completa entre ${reviewed}.`
            : `1 de ${reviewed} reporta esta afirmación completa.`;
      } else {
        coverage = `${reporting} de ${reviewed} reportan esta afirmación.`;
      }
    }

    if (!independent && !authenticPrimary && reporting != null && reporting > 0) {
      limitation = ["Por ahora, no contamos con corroboración independiente.", limitation].filter(Boolean).join(" ");
    }

    if (
      explanation === "No se pudo establecer que aporten confirmaciones independientes." ||
      explanation === "Se basan en la misma información original."
    ) {
      explanation = null;
    }
    if (reporting != null && reporting > 1) {
      let commonOrigin = null;
      if (card.known_independent_count === 1 && card.unknown_group_count === 0) {
        commonOrigin = "Estas publicaciones parten de una misma fuente original.";
      } else if ((card.reprint_collapsed_count ?? 0) > 0) {
        commonOrigin = "Algunas de estas publicaciones parten de una misma fuente original.";
      }
      explanation = [explanation, commonOrigin].filter(Boolean).join(" ") || null;
    }
  }

  return { heading, coverage, limitation, explanation, documentaryLimitation };
}

export function officialDocumentDetailIndex(details: ClaimEvidenceDetail[]): number {
  // Only attach the existing limitation when a single non-supporting official
  // document can be identified. Consulted documents may be absent from this list.
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
