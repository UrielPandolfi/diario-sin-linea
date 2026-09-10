"use client";

import { claimsForIds, editorialLabelCopy } from "@/features/article/claim-status";
import type { ArticleBodyBlock, ArticleClaim, ClaimCardPresentation } from "@/lib/api/types";
import { useEffect, useId, useRef, useState } from "react";

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
        <p key={blockIndex} className="font-sans text-[17px] leading-[1.65] text-primary">
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
        </p>
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
  const rootRef = useRef<HTMLSpanElement>(null);
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
    <span ref={rootRef} className="relative inline">
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
        <span
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
        </span>
      ) : null}
    </span>
  );
}

function ClaimPopoverItem({ claim, divided }: { claim: ArticleClaim; divided: boolean }) {
  const card = claim.presentation;
  const editorialLabels = claim.editorial_labels ?? [];
  const falseAssertions = claim.false_assertions ?? [];
  const verificationLabel = card?.verification_label ?? "Independencia desconocida";
  const coverage = card?.coverage ?? "No hay desglose de independencia para esta verificación.";
  const details = card?.evidence_detail ?? [];

  return (
    <span className={divided ? "mt-3 block border-t border-border pt-3" : "block"}>
      <span className="block font-sans text-sm leading-snug text-primary">{claim.canonical_text}</span>
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
      <span className="mt-1.5 block font-sans text-sm leading-snug text-accent-petrol">{verificationLabel}</span>
      {card?.limitation ? (
        <span className="mt-1 block font-sans text-xs leading-snug text-secondary">{card.limitation}</span>
      ) : null}
      <span className="mt-1.5 block font-sans text-xs leading-snug text-secondary">{coverage}</span>
      {card?.explanation ? (
        <span className="mt-1 block font-sans text-xs leading-snug text-secondary">{card.explanation}</span>
      ) : null}
      {claim.verification?.unresolved ? (
        <span className="mt-1 block font-sans text-xs text-secondary">Sin resolver</span>
      ) : null}
      {falseAssertions.map((row) => (
        <span key={row.source_item_id} className="mt-1.5 block font-sans text-xs leading-snug text-secondary">
          {row.source_name}: “{row.excerpt}”
        </span>
      ))}
      {details.length > 0 ? <EvidenceDetails details={details} documentNoun={card?.document_noun} /> : null}
    </span>
  );
}

function EvidenceDetails({
  details,
  documentNoun,
}: {
  details: NonNullable<ClaimCardPresentation["evidence_detail"]>;
  documentNoun?: string;
}) {
  const noun = documentNoun === "medios" ? "medios" : "documentos";
  return (
    <details
      className="mt-2"
      onClick={(event) => event.stopPropagation()}
      onKeyDown={(event) => event.stopPropagation()}
    >
      <summary className="cursor-pointer font-sans text-xs text-accent-petrol">
        Detalle de {noun} consultados
      </summary>
      <ul className="mt-1.5 list-disc space-y-1 pl-4">
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
          </li>
        ))}
      </ul>
    </details>
  );
}
