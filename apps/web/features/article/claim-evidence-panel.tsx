"use client";

import {
  EMPTY_DOCUMENTS,
  UNKNOWN_COVERAGE,
  claimEvidenceCopy,
  documentsAvailability,
  officialDocumentDetailIndex,
  type ClaimEvidenceCopy,
} from "./claim-popover-copy";
import type { ArticleClaim, ClaimEvidenceDetail } from "../../lib/api/types";
import { FileText } from "lucide-react";
import { useId, useState } from "react";

export function ClaimEvidenceList({ claims }: { claims: ArticleClaim[] }) {
  if (claims.length === 0) {
    const copy = claimEvidenceCopy(null);
    return (
      <article className="font-sans">
        <p className="text-[11px] font-medium uppercase tracking-[0.14em] text-muted">Respaldo de esta afirmación</p>
        <h3 className="mt-3 font-heading text-[1.35rem] font-semibold leading-snug text-primary">{copy.heading}</h3>
        <p className="mt-2 text-sm leading-relaxed text-secondary">{copy.explanation}</p>
      </article>
    );
  }
  return (
    <ul className="space-y-0" aria-label={claims.length > 1 ? "Afirmaciones de este pasaje" : undefined}>
      {claims.map((claim, index) => (
        <li key={claim.id} className={index > 0 ? "mt-4 border-t border-border pt-4" : ""}>
          <ClaimEvidencePanel claim={claim} showCanonical={claims.length > 1} />
        </li>
      ))}
    </ul>
  );
}

function compactDocuments(copy: ClaimEvidenceCopy): ClaimEvidenceDetail[] {
  if (documentsAvailability(copy) !== "listed") return [];
  return copy.documents.slice(0, 2);
}

function sourceSectionLabel(rows: ClaimEvidenceDetail[]): string {
  const allSupport = rows.length > 0 && rows.every((row) => row.evidence_type === "SUPPORTS");
  if (rows.length === 1 && allSupport) return "Publicación que la respalda";
  if (allSupport) return "Publicaciones que la respaldan";
  return "Publicaciones consultadas";
}

function hasExpandableDetail(copy: ClaimEvidenceCopy): boolean {
  const availability = documentsAvailability(copy);
  const extraDocuments = copy.documents.length > compactDocuments(copy).length;
  return Boolean(
    extraDocuments ||
      copy.coverage ||
      copy.verifiedScope ||
      copy.unsupportedScope ||
      copy.documentaryLimitation ||
      availability === "empty",
  );
}

export function ClaimEvidencePanel({
  claim,
  showCanonical = false,
}: {
  claim: ArticleClaim;
  showCanonical?: boolean;
}) {
  const copy = claimEvidenceCopy(claim);
  const availability = documentsAvailability(copy);
  const officialIndex = copy.documentaryLimitation ? officialDocumentDetailIndex(copy.documents) : -1;
  const compact = compactDocuments(copy);
  const expandable = hasExpandableDetail(copy);
  const [open, setOpen] = useState(false);
  const detailsId = useId();
  const highlightNote =
    copy.missingPresentation || copy.kind === "unevaluated" || copy.verifiedScope || copy.unsupportedScope
      ? null
      : "El respaldo se refiere al texto resaltado.";

  return (
    <article className="font-sans text-[15px]" data-presentation-kind={copy.kind ?? "unknown"}>
      <p className="text-[11px] font-medium uppercase tracking-[0.14em] text-muted">Respaldo de esta afirmación</p>
      <div className="mt-3">
        <span className="status-chip" data-kind={copy.kind ?? "unknown"}>
          {copy.heading}
        </span>
      </div>
      <h3 className="mt-3 font-heading text-[1.35rem] font-semibold leading-snug text-primary">{copy.heading}</h3>
      {showCanonical && copy.canonicalText ? (
        <p className="mt-2 text-sm leading-relaxed text-secondary">{copy.canonicalText}</p>
      ) : null}
      {copy.explanation ? (
        <p className="mt-2 text-[15px] leading-[1.55] text-secondary">{copy.explanation}</p>
      ) : null}
      {copy.limitation ? <p className="mt-2 text-sm leading-relaxed text-secondary">{copy.limitation}</p> : null}
      {copy.verifiedScope ? (
        <p className="mt-3 text-sm leading-relaxed text-secondary">
          Alcance establecido: «{copy.verifiedScope}».
        </p>
      ) : null}
      {copy.unsupportedScope ? (
        <p className="mt-2 text-sm leading-relaxed text-secondary">
          Alcance pendiente: «{copy.unsupportedScope}».
        </p>
      ) : null}

      {compact.length > 0 ? (
        <div className="mt-4 border-t border-border pt-3">
          <p className="text-[11px] font-medium uppercase tracking-[0.12em] text-muted">
            {sourceSectionLabel(compact)}
          </p>
          <ul className="mt-2 space-y-2">
            {compact.map((row, index) => (
              <SourceRow key={`${row.url ?? row.name ?? index}-${row.evidence_type}`} row={row} />
            ))}
          </ul>
        </div>
      ) : null}

      {highlightNote ? <p className="mt-3 text-xs leading-relaxed text-muted">{highlightNote}</p> : null}

      {expandable ? (
        <div className="mt-4">
          <button
            type="button"
            className="sl-btn-primary"
            aria-expanded={open}
            aria-controls={detailsId}
            onClick={() => setOpen((current) => !current)}
          >
            {open ? "Ocultar evidencia y detalles" : "Ver evidencia y detalles"}
          </button>
          {open ? (
            <div id={detailsId} className="mt-3 space-y-2 border-t border-border pt-3">
              {availability === "unknown" ? (
                <p className="text-sm leading-relaxed text-secondary">{copy.coverage || UNKNOWN_COVERAGE}</p>
              ) : null}
              {availability === "empty" ? (
                <p className="text-sm leading-relaxed text-secondary">{EMPTY_DOCUMENTS}</p>
              ) : null}
              {availability === "listed" && copy.coverage ? (
                <p className="text-sm leading-relaxed text-secondary">{copy.coverage}</p>
              ) : null}
              {copy.canonicalText ? (
                <p className="text-sm leading-relaxed text-secondary">
                  <span className="text-muted">Afirmación. </span>
                  {copy.canonicalText}
                </p>
              ) : null}
              {copy.documents.length > 0 ? (
                <ul className="space-y-2">
                  {copy.documents.map((row, index) => (
                    <li key={`${row.url ?? row.name ?? index}-${row.evidence_type}`}>
                      <SourceRow row={row} stance />
                      {index === officialIndex && copy.documentaryLimitation ? (
                        <span className="mt-1 block text-sm text-secondary">{copy.documentaryLimitation}</span>
                      ) : null}
                    </li>
                  ))}
                </ul>
              ) : null}
              {copy.documentaryLimitation && officialIndex === -1 ? (
                <p className="text-sm leading-relaxed text-secondary">{copy.documentaryLimitation}</p>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}

function SourceRow({ row, stance = false }: { row: ClaimEvidenceDetail; stance?: boolean }) {
  const name = row.name || "Publicación consultada";
  return (
    <div className="flex items-start gap-2.5">
      <FileText className="mt-0.5 h-4 w-4 shrink-0 text-muted" strokeWidth={1.7} aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="break-words text-sm leading-snug text-primary">{name}</p>
        {stance && row.stance ? <p className="mt-0.5 text-xs text-secondary">{row.stance}</p> : null}
        {row.url ? (
          <a
            href={row.url}
            className="mt-0.5 inline-flex items-center gap-1 text-xs text-accent hover:text-accent-blue"
            target="_blank"
            rel="noreferrer"
          >
            Abrir fuente
            <span aria-hidden>↗</span>
          </a>
        ) : (
          <p className="text-xs text-muted">Publicación consultada</p>
        )}
      </div>
    </div>
  );
}
