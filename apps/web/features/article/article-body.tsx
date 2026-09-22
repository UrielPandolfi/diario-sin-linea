"use client";

import { ClaimEvidenceList } from "./claim-evidence-panel";
import { ClaimEvidenceOverlay } from "./claim-evidence-overlay";
import { hoverDelayMs } from "./claim-popover-copy";
import { claimsForIds } from "./claim-status";
import { focusableElements } from "./evidence-focus";
import { useEvidenceSurface } from "./use-evidence-surface";
import type { ArticleBodyBlock, ArticleClaim } from "../../lib/api/types";
import { Info } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

function evidenceTriggerLabel(text: string): string {
  const trimmed = text.trim();
  const needsStop = !/[.!?…]$/.test(trimmed);
  return `${trimmed}${needsStop ? "." : ""} Consultar respaldo`;
}

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
  sourceKey,
}: {
  body: string;
  bodyBlocks?: ArticleBodyBlock[] | null;
  claims?: ArticleClaim[];
  sourceKey?: string;
}) {
  const [openKey, setOpenKey] = useState<string | null>(null);
  const surface = useEvidenceSurface();
  const previousSurface = useRef<"popover" | "sheet" | null>(null);

  useEffect(() => {
    setOpenKey(null);
  }, [sourceKey]);

  useEffect(() => {
    if (previousSurface.current && surface && previousSurface.current !== surface) {
      setOpenKey(null);
    }
    previousSurface.current = surface;
  }, [surface]);

  if (!bodyBlocks?.length) {
    const paragraphs = splitPlainBody(body);
    if (paragraphs.length === 0) return null;
    return (
      <div className="article-body mt-6 space-y-5">
        {paragraphs.map((paragraph, index) => (
          <p key={index}>{paragraph}</p>
        ))}
      </div>
    );
  }

  return (
    <div className="article-body mt-6 space-y-5" data-evidence-mode={surface ?? "pending"}>
      {bodyBlocks.map((block, blockIndex) => {
        const hasClaims = (block.segments ?? []).some((segment) => (segment.claim_ids ?? []).length > 0);
        const Tag = hasClaims ? "div" : "p";
        return (
          <Tag key={blockIndex}>
            {(block.segments ?? []).map((segment, segmentIndex) => {
              const key = `${blockIndex}-${segmentIndex}`;
              const matched = claimsForIds(segment.claim_ids ?? [], claims);
              if ((segment.claim_ids ?? []).length > 0 && matched.length === 0) {
                return <span key={key}>{segment.text}</span>;
              }
              if (matched.length === 0) {
                return <span key={key}>{segment.text}</span>;
              }
              return (
                <ClaimSegment
                  key={key}
                  segmentKey={key}
                  text={segment.text}
                  claims={matched}
                  surface={surface ?? "sheet"}
                  open={openKey === key}
                  onOpen={() => setOpenKey(key)}
                  onClose={() => setOpenKey((current) => (current === key ? null : current))}
                />
              );
            })}
          </Tag>
        );
      })}
    </div>
  );
}

function ClaimSegment({
  segmentKey,
  text,
  claims,
  surface,
  open,
  onOpen,
  onClose,
}: {
  segmentKey: string;
  text: string;
  claims: ArticleClaim[];
  surface: "popover" | "sheet";
  open: boolean;
  onOpen: () => void;
  onClose: () => void;
}) {
  const dialogId = useId();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const closeTimer = useRef<number | null>(null);
  const openTimer = useRef<number | null>(null);
  const restoreFocus = useRef(false);
  const ignoreFocusOpen = useRef(false);
  const [pinned, setPinned] = useState(false);
  const [openedByKeyboard, setOpenedByKeyboard] = useState(false);

  function clearCloseTimer() {
    if (closeTimer.current !== null) {
      window.clearTimeout(closeTimer.current);
      closeTimer.current = null;
    }
  }

  function clearOpenTimer() {
    if (openTimer.current !== null) {
      window.clearTimeout(openTimer.current);
      openTimer.current = null;
    }
  }

  function scheduleClose() {
    if (pinned) return;
    clearOpenTimer();
    clearCloseTimer();
    const delay = hoverDelayMs("close");
    if (delay <= 0) {
      restoreFocus.current = false;
      onClose();
      return;
    }
    closeTimer.current = window.setTimeout(() => {
      restoreFocus.current = false;
      onClose();
    }, delay);
  }

  function scheduleOpen() {
    if (surface !== "popover") return;
    clearCloseTimer();
    if (open) return;
    clearOpenTimer();
    const delay = hoverDelayMs("open");
    if (delay <= 0) {
      onOpen();
      return;
    }
    openTimer.current = window.setTimeout(() => {
      onOpen();
    }, delay);
  }

  function armIgnoreFocusOpen() {
    ignoreFocusOpen.current = true;
    window.setTimeout(() => {
      ignoreFocusOpen.current = false;
    }, 50);
  }

  function close(options?: { restore?: boolean }) {
    clearCloseTimer();
    clearOpenTimer();
    restoreFocus.current = options?.restore ?? false;
    if (restoreFocus.current) armIgnoreFocusOpen();
    setPinned(false);
    setOpenedByKeyboard(false);
    onClose();
  }

  useEffect(() => () => {
    clearCloseTimer();
    clearOpenTimer();
  }, []);

  useEffect(() => {
    if (!open) {
      setPinned(false);
      setOpenedByKeyboard(false);
    }
  }, [open]);

  useEffect(() => {
    if (!open || surface !== "popover") return;
    function onPointerDown(event: PointerEvent) {
      const target = event.target as Node | null;
      if (!target) return;
      if (triggerRef.current?.contains(target) || panelRef.current?.contains(target)) return;
      const bridge = document.querySelector("[data-evidence-bridge]");
      if (bridge?.contains(target)) return;
      restoreFocus.current = false;
      setPinned(false);
      setOpenedByKeyboard(false);
      onClose();
    }
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open, surface, onClose]);

  function activate(source: "keyboard" | "pointer") {
    clearCloseTimer();
    clearOpenTimer();
    if (surface === "sheet") {
      if (open) {
        close({ restore: source === "keyboard" });
        return;
      }
      restoreFocus.current = true;
      setPinned(true);
      setOpenedByKeyboard(source === "keyboard");
      onOpen();
      return;
    }
    if (!open) {
      restoreFocus.current = source === "keyboard";
      setPinned(true);
      setOpenedByKeyboard(source === "keyboard");
      onOpen();
      return;
    }
    if (!pinned) {
      restoreFocus.current = source === "keyboard";
      setPinned(true);
      setOpenedByKeyboard(source === "keyboard");
      return;
    }
    close({ restore: source === "keyboard" });
  }

  const title = claims.length > 1 ? "Respaldo de las afirmaciones" : "Respaldo de la afirmación";

  return (
    <span className="relative inline">
      <button
        ref={triggerRef}
        type="button"
        aria-expanded={open}
        aria-controls={open ? dialogId : undefined}
        aria-haspopup="dialog"
        aria-label={evidenceTriggerLabel(text)}
        data-claim-segment={segmentKey}
        data-open={open ? "true" : "false"}
        className="claim-trigger"
        onMouseEnter={scheduleOpen}
        onMouseLeave={() => {
          if (surface === "popover") scheduleClose();
        }}
        onFocus={() => {
          if (ignoreFocusOpen.current) return;
          if (surface === "popover") {
            clearCloseTimer();
            onOpen();
          }
        }}
        onBlur={(event) => {
          if (surface !== "popover" || pinned) return;
          const next = event.relatedTarget as Node | null;
          if (next && (triggerRef.current?.contains(next) || panelRef.current?.contains(next))) return;
          scheduleClose();
        }}
        onClick={(event) => {
          event.preventDefault();
          event.stopPropagation();
          activate("pointer");
        }}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            event.stopPropagation();
            activate("keyboard");
            return;
          }
          if (event.key === "Tab" && !event.shiftKey && open && surface === "popover") {
            const first = focusableElements(panelRef.current)[0] ?? panelRef.current;
            if (first) {
              event.preventDefault();
              first.focus();
            }
          }
        }}
      >
        {text}
        <Info className="claim-info" strokeWidth={1.75} aria-hidden />
      </button>
      <ClaimEvidenceOverlay
        open={open}
        surface={surface}
        title={title}
        dialogId={dialogId}
        triggerRef={triggerRef}
        panelRef={panelRef}
        restoreFocusRef={restoreFocus}
        moveFocus={open && (surface === "sheet" || openedByKeyboard)}
        onClose={() => close({ restore: true })}
        onDismiss={() => close({ restore: surface === "sheet" })}
        onContentEnter={() => {
          clearOpenTimer();
          clearCloseTimer();
        }}
        onContentLeave={() => {
          if (surface === "popover") scheduleClose();
        }}
      >
        <ClaimEvidenceList claims={claims} />
      </ClaimEvidenceOverlay>
    </span>
  );
}
