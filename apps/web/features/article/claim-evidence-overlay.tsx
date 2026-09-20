"use client";

import { placePopover } from "./claim-popover-copy";
import { focusableElements } from "./evidence-focus";
import { X } from "lucide-react";
import {
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";

export function ClaimEvidenceOverlay({
  open,
  surface,
  title,
  dialogId,
  triggerRef,
  panelRef,
  restoreFocusRef,
  moveFocus,
  onClose,
  onDismiss,
  onContentEnter,
  onContentLeave,
  children,
}: {
  open: boolean;
  surface: "popover" | "sheet";
  title: string;
  dialogId: string;
  triggerRef: { current: HTMLElement | null };
  panelRef: { current: HTMLDivElement | null };
  restoreFocusRef: { current: boolean };
  moveFocus: boolean;
  onClose: () => void;
  onDismiss: () => void;
  onContentEnter?: () => void;
  onContentLeave?: () => void;
  children: ReactNode;
}) {
  const titleId = useId();
  const previousOverflow = useRef<string>("");
  const wasOpen = useRef(false);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useLayoutEffect(() => {
    if (!open || surface !== "popover") return;
    function align() {
      const panel = panelRef.current;
      const trigger = triggerRef.current;
      if (!panel || !trigger) return;
      const next = placePopover(
        trigger.getBoundingClientRect(),
        { width: panel.offsetWidth || 320, height: panel.offsetHeight || 240 },
        { width: document.documentElement.clientWidth || window.innerWidth, height: document.documentElement.clientHeight || window.innerHeight },
      );
      const top = `${next.top}px`;
      const left = `${next.left}px`;
      if (panel.style.top !== top) panel.style.top = top;
      if (panel.style.left !== left) panel.style.left = left;
    }
    align();
    window.addEventListener("resize", align);
    window.addEventListener("scroll", align, true);
    return () => {
      window.removeEventListener("resize", align);
      window.removeEventListener("scroll", align, true);
    };
  }, [open, surface, panelRef, triggerRef]);

  useEffect(() => {
    if (!open || surface !== "sheet") return;
    previousOverflow.current = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previousOverflow.current;
    };
  }, [open, surface]);

  useEffect(() => {
    if (!open) return;
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  useEffect(() => {
    if (!open || surface !== "sheet") return;
    const panel = panelRef.current;
    if (!panel) return;
    function onKey(event: KeyboardEvent) {
      if (event.key !== "Tab" || !panelRef.current) return;
      const nodes = focusableElements(panelRef.current);
      if (nodes.length === 0) {
        event.preventDefault();
        panelRef.current.focus();
        return;
      }
      const first = nodes[0];
      const last = nodes[nodes.length - 1];
      const active = document.activeElement;
      if (event.shiftKey && (active === first || !panelRef.current.contains(active))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
      }
    }
    panel.addEventListener("keydown", onKey);
    return () => panel.removeEventListener("keydown", onKey);
  }, [open, surface, panelRef]);

  useEffect(() => {
    if (open) {
      wasOpen.current = true;
      if (moveFocus) {
        panelRef.current?.focus();
      }
      return;
    }
    if (!wasOpen.current) return;
    wasOpen.current = false;
    if (!restoreFocusRef.current) return;
    const trigger = triggerRef.current;
    if (trigger && document.contains(trigger)) trigger.focus();
  }, [open, moveFocus, panelRef, triggerRef, restoreFocusRef]);

  if (!open || typeof document === "undefined") return null;

  function onPanelKeyDown(event: ReactKeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") {
      event.stopPropagation();
      onClose();
      return;
    }
    if (surface !== "popover" || event.key !== "Tab") return;
    const nodes = focusableElements(panelRef.current);
    const first = nodes[0];
    const last = nodes[nodes.length - 1];
    if (event.shiftKey && (document.activeElement === first || document.activeElement === panelRef.current)) {
      event.preventDefault();
      triggerRef.current?.focus();
      return;
    }
    if (!event.shiftKey && document.activeElement === last) {
      onContentLeave?.();
    }
  }

  const closeButton = (
    <button
      type="button"
      onClick={onClose}
      className={
        surface === "sheet"
          ? "inline-flex min-h-11 min-w-11 shrink-0 items-center justify-center rounded-sm text-secondary hover:bg-hover hover:text-primary"
          : "inline-flex shrink-0 items-center justify-center rounded-sm p-2 text-secondary hover:bg-hover hover:text-primary"
      }
      aria-label="Cerrar"
    >
      <X className="h-4 w-4" aria-hidden />
    </button>
  );

  if (surface === "sheet") {
    return createPortal(
      <div className="fixed inset-0 z-50" data-evidence-surface="sheet">
        <div
          aria-hidden="true"
          className="absolute inset-0 bg-background/70"
          onClick={onDismiss}
        />
        <div
          ref={panelRef}
          id={dialogId}
          role="dialog"
          aria-modal="true"
          aria-labelledby={titleId}
          tabIndex={-1}
          onKeyDown={onPanelKeyDown}
          className="absolute inset-x-0 bottom-0 flex max-h-[min(85dvh,calc(100dvh-env(safe-area-inset-top)))] w-full min-w-0 flex-col border-t border-border bg-surface shadow-lg outline-none"
        >
          <div className="flex items-center justify-between gap-3 border-b border-border bg-surface px-4 py-3">
            <h2 id={titleId} className="font-heading text-base text-primary">
              {title}
            </h2>
            {closeButton}
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3 pb-[max(1.25rem,env(safe-area-inset-bottom))]">
            {children}
          </div>
        </div>
      </div>,
      document.body,
    );
  }

  return createPortal(
    <div
      ref={panelRef}
      id={dialogId}
      role="dialog"
      aria-modal="false"
      aria-labelledby={titleId}
      tabIndex={-1}
      data-evidence-surface="popover"
      onMouseEnter={onContentEnter}
      onMouseLeave={onContentLeave}
      onKeyDown={onPanelKeyDown}
      className="fixed z-50 w-96 max-h-[min(24rem,70vh)] max-w-[calc(100vw-2rem)] overflow-y-auto rounded-md border border-border bg-surface p-3 shadow-lg outline-none"
    >
      <div className="mb-2 flex items-start justify-between gap-2">
        <h2 id={titleId} className="font-heading text-sm text-primary">
          {title}
        </h2>
        {closeButton}
      </div>
      {children}
    </div>,
    document.body,
  );
}
