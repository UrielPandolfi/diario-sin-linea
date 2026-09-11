"use client";

import { claimsForIds, editorialLabelCopy } from "@/features/article/claim-status";
import { claimPopoverCopy, officialDocumentDetailIndex } from "@/features/article/claim-popover-copy";
import type { ArticleBodyBlock, ArticleClaim, ClaimCardPresentation } from "@/lib/api/types";
import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";

function splitPlainBody(body: string): string[] {
  return body
    .split(/\n{2,}/)
    .map((part) => part.trim())
    .filter(Boolean);
}

export function ArticleBody({
  body,
  bodyBlocks,
  claims,
}: {
  body: string;
  bodyBlocks?: ArticleBodyBlock[] | null;
  claims?: ArticleClaim[];
}) {
  const [openKey, setOpenKey] = useState<string | null>(null);

  useEffect(() => {
    if (!openKey) return;
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") setOpenKey(null);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [openKey]);

  if (!bodyBlocks?.length) {
    const paragraphs = splitPlainBody(body);
    if (paragraphs.length === 0) return null;
    return (
      <div className="mt-6 space-y-4">
        {paragraphs.map((paragraph, index) => (
          <p key={index} className="font-sans text-[17px] leading-[1.65] text-primary">
            {paragraph}
          </p>
        ))}
      </div>
    );
  }

  return (
    <div className="mt-6 space-y-4">
      {bodyBlocks.map((block, blockIndex) => (
        <div key={blockIndex} className="font-sans text-[17px] leading-[1.65] text-primary">
          {(block.segments ?? []).map((segment, segmentIndex) => {
            const key = `${blockIndex}-${segmentIndex}`;
            const matched = claimsForIds(segment.claim_ids ?? [], claims);
            if (matched.length === 0) {
              return <span key={key}>{segment.text}</span>;
            }
            return (
              <ClaimSegment
                key={key}
                segmentKey={key}
                text={segment.text}
                claims={matched}
                open={openKey === key}
                onOpen={() => setOpenKey(key)}
                onClose={() => setOpenKey((current) => (current === key ? null : current))}
                onToggle={() => setOpenKey((current) => (current === key ? null : key))}
              />
            );
          })}
        </div>
      ))}
    </div>
  );
}

function ClaimSegment({
  segmentKey,
  text,
  claims,
  open,
  onOpen,
  onClose,
  onToggle,
}: {
  segmentKey: string;
  text: string;
  claims: ArticleClaim[];
  open: boolean;
  onOpen: () => void;
  onClose: () => void;
  onToggle: () => void;
}) {
  const popoverId = useId();
  const rootRef = useRef<HTMLDivElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);
  const closeTimer = useRef<number | null>(null);

  function clearCloseTimer() {
    if (closeTimer.current !== null) {
      window.clearTimeout(closeTimer.current);
      closeTimer.current = null;
    }
  }

  function scheduleClose() {
    clearCloseTimer();
    closeTimer.current = window.setTimeout(() => onClose(), 160);
  }

  useEffect(() => () => clearCloseTimer(), []);

  useLayoutEffect(() => {
    if (!open) return;
    function alignPopover() {
      const popover = popoverRef.current;
      if (!popover) return;
      popover.style.transform = "";
      const rect = popover.getBoundingClientRect();
      const rightEdge = document.documentElement.clientWidth - 16;
      const offset = Math.max(16 - rect.left, Math.min(0, rightEdge - rect.right));
      popover.style.transform = `translateX(${offset}px)`;
    }
    alignPopover();
    window.addEventListener("resize", alignPopover);
    return () => window.removeEventListener("resize", alignPopover);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: PointerEvent) {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        onClose();
      }
    }
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open, onClose]);

  return (
    <div ref={rootRef} className="relative inline">
      <span
        tabIndex={0}
        role="button"
        aria-expanded={open}
        aria-controls={popoverId}
        aria-haspopup="dialog"
        data-claim-segment={segmentKey}
        className="cursor-help rounded-[2px] underline decoration-dotted decoration-border underline-offset-[0.28em] transition-colors duration-150 hover:bg-hover focus-visible:bg-hover"
        onMouseEnter={() => {
          clearCloseTimer();
          onOpen();
        }}
        onMouseLeave={scheduleClose}
        onClick={(event) => {
          event.stopPropagation();
          if (window.matchMedia("(hover: hover) and (pointer: fine)").matches) return;
          onToggle();
        }}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            onToggle();
          }
        }}
      >
        {text}
      </span>
      {open ? (
        <div
          ref={popoverRef}
          id={popoverId}
          role="dialog"
          aria-label="Información de la afirmación"
          className="absolute left-0 top-full z-30 mt-1.5 w-80 max-w-[min(20.5rem,calc(100vw-2rem))] rounded-md border border-border bg-surface p-3 shadow-lg"
          onMouseEnter={clearCloseTimer}
          onMouseLeave={scheduleClose}
        >
          {claims.map((claim, index) => (
            <ClaimPopoverItem key={claim.id} claim={claim} divided={index > 0} />
          ))}
        </div>
      ) : null}
    </div>
  );
}

function ClaimPopoverItem({ claim, divided }: { claim: ArticleClaim; divided: boolean }) {
  const card = claim.presentation;
  const editorialLabels = claim.editorial_labels ?? [];
  const falseAssertions = claim.false_assertions ?? [];
  const copy = claimPopoverCopy(claim);
  const details = card?.evidence_detail ?? [];

  return (
    <div className={divided ? "mt-3 border-t border-border pt-3" : ""}>
      <span className="block font-sans text-sm font-semibold leading-snug text-primary">{copy.heading}</span>
      <span className="mt-2 block font-sans text-xs leading-relaxed text-primary">{copy.coverage}</span>
      {copy.limitation ? (
        <span className="mt-2 block font-sans text-xs leading-relaxed text-secondary">{copy.limitation}</span>
      ) : null}
      {copy.explanation ? (
        <span className="mt-1 block font-sans text-xs leading-relaxed text-secondary">{copy.explanation}</span>
      ) : null}
      {editorialLabels.length > 0 ? (
        <span className="mt-1.5 flex flex-wrap gap-1">
          {editorialLabels.map((label) => (
            <span
              key={label}
              className="border border-border px-1.5 py-0.5 font-sans text-[10px] uppercase tracking-[0.12em] text-accent-petrol"
            >
              {editorialLabelCopy(label)}
            </span>
          ))}
        </span>
      ) : null}
      {claim.verification?.unresolved ? (
        <span className="mt-1 block font-sans text-xs text-secondary">Sin resolver</span>
      ) : null}
      {falseAssertions.map((row) => (
        <span key={row.source_item_id} className="mt-1.5 block font-sans text-xs leading-snug text-secondary">
          {row.source_name}: “{row.excerpt}”
        </span>
      ))}
      <EvidenceDetails
        details={details}
        canonicalText={claim.canonical_text}
        documentaryLimitation={copy.documentaryLimitation}
      />
    </div>
  );
}

function EvidenceDetails({
  details,
  canonicalText,
  documentaryLimitation,
}: {
  details: NonNullable<ClaimCardPresentation["evidence_detail"]>;
  canonicalText: string;
  documentaryLimitation: string | null;
}) {
  const officialDocumentIndex = documentaryLimitation ? officialDocumentDetailIndex(details) : -1;
  return (
    <details
      className="mt-3 border-t border-border pt-2"
      onClick={(event) => event.stopPropagation()}
      onKeyDown={(event) => event.stopPropagation()}
    >
      <summary className="cursor-pointer font-sans text-xs font-medium text-secondary hover:text-primary">
        Ver documentos y detalles del respaldo
      </summary>
      <span className="mt-2 block font-sans text-xs leading-relaxed text-secondary">{canonicalText}</span>
      {details.length > 0 ? (
        <ul className="mt-2 list-disc space-y-2 pl-4">
          {details.map((row, index) => (
            <li key={`${row.url ?? row.name ?? index}-${row.evidence_type}`} className="font-sans text-xs leading-snug text-secondary">
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
              {index === officialDocumentIndex ? (
                <span className="mt-1 block">{documentaryLimitation}</span>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
      {documentaryLimitation && officialDocumentIndex === -1 ? (
        <span className="mt-2 block font-sans text-xs leading-relaxed text-secondary">{documentaryLimitation}</span>
      ) : null}
    </details>
  );
}
