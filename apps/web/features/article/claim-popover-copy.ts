import type { ArticleClaim, ClaimEvidenceDetail } from "../../lib/api/types";

const OFFICIAL_LIMITATION_MARKERS = [
  "El documento oficial no sostiene esta proposición.",
  "El documento oficial consultado no sostiene esta proposición.",
];

export const MISSING_PRESENTATION_HEADING = "Información no disponible";
export const MISSING_PRESENTATION_EXPLANATION =
  "No hay información de respaldo para esta afirmación.";
export const UNKNOWN_COVERAGE = "No hay un desglose documental utilizable para esta versión.";
export const EMPTY_DOCUMENTS = "No hay documentos listados para esta afirmación.";

export type ClaimEvidenceCopy = {
  heading: string;
  explanation: string | null;
  limitation: string | null;
  coverage: string | null;
  documentaryLimitation: string | null;
  canonicalText: string | null;
  kind: string | null;
  verifiedScope: string | null;
  unsupportedScope: string | null;
  documents: ClaimEvidenceDetail[];
  documentsKnown: boolean;
  documentsConsulted: number | null;
  documentsSupporting: number | null;
  knownIndependentCount: number | null;
  missingPresentation: boolean;
};

export function claimEvidenceCopy(claim: ArticleClaim | null | undefined): ClaimEvidenceCopy {
  if (!claim) {
    return emptyCopy(true);
  }
  const card = claim.presentation;
  if (!card) {
    return {
      ...emptyCopy(true),
      canonicalText: claim.canonical_text || null,
    };
  }
  const limitation = card.limitation ?? null;
  const documentaryLimitation =
    limitation && OFFICIAL_LIMITATION_MARKERS.includes(limitation) ? limitation : null;
  const verifiedScope = identifiedScope(claim.verified_scope);
  const unsupportedScope = identifiedScope(claim.unsupported_scope);
  return {
    heading: card.verification_label || MISSING_PRESENTATION_HEADING,
    explanation: card.explanation ?? null,
    limitation: documentaryLimitation ? null : limitation,
    coverage: card.coverage ?? null,
    documentaryLimitation,
    canonicalText: claim.canonical_text || null,
    kind: card.presentation_kind ?? null,
    verifiedScope,
    unsupportedScope,
    documents: card.evidence_detail ?? [],
    documentsKnown: card.basis_known === true,
    documentsConsulted: countOrNull(card.documents_consulted),
    documentsSupporting: countOrNull(card.documents_supporting ?? card.documents_reporting),
    knownIndependentCount: countOrNull(card.known_independent_count),
    missingPresentation: false,
  };
}

export function claimPopoverCopy(claim: ArticleClaim) {
  const copy = claimEvidenceCopy(claim);
  return {
    heading: copy.heading,
    explanation: copy.explanation,
    limitation: copy.limitation,
    coverage: copy.coverage,
    documentaryLimitation: copy.documentaryLimitation,
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

export function documentsAvailability(copy: ClaimEvidenceCopy): "unknown" | "empty" | "listed" {
  if (!copy.documentsKnown) return "unknown";
  if (copy.documents.length > 0) return "listed";
  const consulted = copy.documentsConsulted;
  if (consulted === null) return "unknown";
  if (consulted === 0 && copy.documents.length === 0) return "empty";
  return copy.documents.length === 0 ? "empty" : "listed";
}

export const HOVER_OPEN_MS = 180;
export const HOVER_CLOSE_MS = 240;
export const EVIDENCE_SIDE_MIN_WIDTH = 1280;

export function hoverDelayMs(kind: "open" | "close"): number {
  if (typeof globalThis !== "undefined" && typeof (globalThis as { setEvidenceEnv?: unknown }).setEvidenceEnv === "function") {
    return 0;
  }
  return kind === "open" ? HOVER_OPEN_MS : HOVER_CLOSE_MS;
}

export function evidenceSurface(input: { hoverFine: boolean; viewportWidth: number }): "popover" | "sheet" {
  return input.hoverFine && input.viewportWidth >= EVIDENCE_SIDE_MIN_WIDTH ? "popover" : "sheet";
}

export function placePopover(
  trigger: { top: number; left: number; bottom: number; right: number },
  panel: { width: number; height: number },
  viewport: { width: number; height: number },
  gap = 8,
): { top: number; left: number } {
  const margin = 16;
  let top = trigger.bottom + gap;
  if (top + panel.height > viewport.height - margin) {
    top = Math.max(margin, trigger.top - gap - panel.height);
  }
  let left = trigger.left;
  if (left + panel.width > viewport.width - margin) {
    left = viewport.width - panel.width - margin;
  }
  if (left < margin) left = margin;
  return { top, left };
}

export function placeSidePopover(
  trigger: { top: number; left: number; bottom: number; right: number; height?: number },
  panel: { width: number; height: number },
  viewport: { width: number; height: number },
  slot?: { left: number; width: number } | null,
): { top: number; left: number; arrow: number } {
  const margin = 16;
  const left =
    slot && slot.width >= 240
      ? slot.left
      : Math.min(Math.max(trigger.right + 16, margin), viewport.width - panel.width - margin);
  let top = trigger.top - 12;
  top = Math.min(top, viewport.height - panel.height - margin);
  top = Math.max(margin, top);
  const triggerMid = trigger.top + (trigger.height ?? trigger.bottom - trigger.top) / 2;
  const arrow = Math.min(Math.max(triggerMid - top, 22), Math.max(22, panel.height - 22));
  return { top, left, arrow };
}

export function hoverBridgeRect(
  trigger: { top: number; left: number; bottom: number; right: number },
  panel: { top: number; left: number; bottom: number; right: number },
): { top: number; left: number; width: number; height: number } | null {
  const left = Math.min(trigger.right, panel.left);
  const right = Math.max(trigger.right, panel.left);
  const width = right - left;
  if (width <= 0) return null;
  const top = Math.min(trigger.top, panel.top);
  const bottom = Math.max(trigger.bottom, panel.bottom);
  return { top, left, width, height: Math.max(1, bottom - top) };
}

function identifiedScope(value: string | null | undefined): string | null {
  const text = (value ?? "").trim();
  return text ? text : null;
}

function countOrNull(value: number | null | undefined): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function emptyCopy(missingPresentation: boolean): ClaimEvidenceCopy {
  return {
    heading: MISSING_PRESENTATION_HEADING,
    explanation: MISSING_PRESENTATION_EXPLANATION,
    limitation: null,
    coverage: null,
    documentaryLimitation: null,
    canonicalText: null,
    kind: null,
    verifiedScope: null,
    unsupportedScope: null,
    documents: [],
    documentsKnown: false,
    documentsConsulted: null,
    documentsSupporting: null,
    knownIndependentCount: null,
    missingPresentation,
  };
}
