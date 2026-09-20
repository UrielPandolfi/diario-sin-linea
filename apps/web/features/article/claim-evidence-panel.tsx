"use client";

import {
  EMPTY_DOCUMENTS,
  UNKNOWN_COVERAGE,
  claimEvidenceCopy,
  documentsAvailability,
  officialDocumentDetailIndex,
} from "./claim-popover-copy";
import type { ArticleClaim } from "../../lib/api/types";

export function ClaimEvidenceList({ claims }: { claims: ArticleClaim[] }) {
  if (claims.length === 0) {
    const copy = claimEvidenceCopy(null);
    return (
      <article className="font-sans">
        <h3 className="text-sm font-semibold leading-snug text-primary">{copy.heading}</h3>
        <p className="mt-2 text-xs leading-relaxed text-secondary">{copy.explanation}</p>
      </article>
    );
  }
  return (
    <ul className="space-y-0" aria-label={claims.length > 1 ? "Afirmaciones de este pasaje" : undefined}>
      {claims.map((claim, index) => (
        <li
          key={claim.id}
          className={index > 0 ? "mt-3 border-t border-border pt-3" : ""}
        >
          <ClaimEvidencePanel claim={claim} />
        </li>
      ))}
    </ul>
  );
}

export function ClaimEvidencePanel({ claim }: { claim: ArticleClaim }) {
  const copy = claimEvidenceCopy(claim);
  const availability = documentsAvailability(copy);
  const officialIndex = copy.documentaryLimitation
    ? officialDocumentDetailIndex(copy.documents)
    : -1;

  return (
    <article className="font-sans" data-presentation-kind={copy.kind ?? "unknown"}>
      {copy.canonicalText ? (
        <p className="text-xs leading-relaxed text-secondary">
          <span className="text-muted">Afirmación. </span>
          {copy.canonicalText}
        </p>
      ) : null}
      <h3 className="mt-2 text-sm font-semibold leading-snug text-primary">{copy.heading}</h3>
      {copy.explanation ? (
        <div className="mt-2">
          <p className="text-[10px] uppercase tracking-[0.12em] text-muted">Qué significa</p>
          <p className="mt-1 text-xs leading-relaxed text-primary">{copy.explanation}</p>
        </div>
      ) : null}
      {copy.limitation ? (
        <p className="mt-2 text-xs leading-relaxed text-secondary">{copy.limitation}</p>
      ) : null}
      <details className="mt-3 border-t border-border pt-2">
        <summary className="cursor-pointer text-xs font-medium text-secondary hover:text-primary">
          Ver documentos
        </summary>
        <div className="mt-2 space-y-2">
          {availability === "unknown" ? (
            <p className="text-xs leading-relaxed text-secondary">{copy.coverage || UNKNOWN_COVERAGE}</p>
          ) : null}
          {availability === "empty" ? (
            <p className="text-xs leading-relaxed text-secondary">{EMPTY_DOCUMENTS}</p>
          ) : null}
          {availability === "listed" && copy.coverage ? (
            <p className="text-xs leading-relaxed text-secondary">{copy.coverage}</p>
          ) : null}
          {copy.verifiedScope ? (
            <p className="text-xs leading-relaxed text-secondary">
              Quedó establecido: «{copy.verifiedScope}».
            </p>
          ) : null}
          {copy.unsupportedScope ? (
            <p className="text-xs leading-relaxed text-secondary">
              Sin establecer, sin darlo por falso: «{copy.unsupportedScope}».
            </p>
          ) : null}
          {copy.documents.length > 0 ? (
            <ul className="space-y-2">
              {copy.documents.map((row, index) => (
                <li
                  key={`${row.url ?? row.name ?? index}-${row.evidence_type}`}
                  className="text-xs leading-snug text-secondary"
                >
                  <span className="text-primary">{row.stance}</span>
                  {row.name ? ` · ${row.name}` : ""}
                  {row.url ? (
                    <>
                      {" · "}
                      <a href={row.url} className="text-accent-petrol underline" target="_blank" rel="noreferrer">
                        ver
                      </a>
                    </>
                  ) : null}
                  {index === officialIndex && copy.documentaryLimitation ? (
                    <span className="mt-1 block">{copy.documentaryLimitation}</span>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : null}
          {copy.documentaryLimitation && officialIndex === -1 ? (
            <p className="text-xs leading-relaxed text-secondary">{copy.documentaryLimitation}</p>
          ) : null}
        </div>
      </details>
    </article>
  );
}
