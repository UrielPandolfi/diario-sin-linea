"use client";

import { hoverBridgeRect, placeSidePopover } from "./claim-popover-copy";
import { focusableElements } from "./evidence-focus";
import { X } from "lucide-react";
import {
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
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
  const [bridge, setBridge] = useState<{ top: number; left: number; width: number; height: number } | null>(null);

  useLayoutEffect(() => {
    if (!open || surface !== "popover") {
      setBridge(null);
      return;
    }
    function align() {
      const panel = panelRef.current;
      const trigger = triggerRef.current;
      if (!panel || !trigger) return;
      const slot = document.querySelector<HTMLElement>("[data-evidence-column]");
      const slotRect = slot && slot.getClientRects().length > 0 ? slot.getBoundingClientRect() : null;
      const viewport = {
        width: document.documentElement.clientWidth || window.innerWidth,
        height: document.documentElement.clientHeight || window.innerHeight,
      };
      const next = placeSidePopover(
        trigger.getBoundingClientRect(),
        {
          width: slotRect && slotRect.width >= 240 ? slotRect.width : panel.offsetWidth || 360,
          height: panel.offsetHeight || 240,
        },
        viewport,
        slotRect ? { left: slotRect.left, width: slotRect.width } : null,
      );
      const top = `${next.top}px`;
      const left = `${next.left}px`;
      if (slotRect && slotRect.width >= 240) {
        const width = `${slotRect.width}px`;
        if (panel.style.width !== width) panel.style.width = width;
      }
      if (panel.style.top !== top) panel.style.top = top;
      if (panel.style.left !== left) panel.style.left = left;
      panel.style.setProperty("--arrow-top", `${next.arrow}px`);
      const nextBridge = hoverBridgeRect(trigger.getBoundingClientRect(), panel.getBoundingClientRect());
      setBridge((current) => {
        if (
          current &&
          nextBridge &&
          current.top === nextBridge.top &&
          current.left === nextBridge.left &&
          current.width === nextBridge.width &&
          current.height === nextBridge.height
        ) {
          return current;
        }
        return nextBridge;
      });
    }
    align();
    const observer = typeof ResizeObserver === "function" ? new ResizeObserver(align) : null;
    if (panelRef.current) observer?.observe(panelRef.current);
    window.addEventListener("resize", align);
    window.addEventListener("scroll", align, true);
    return () => {
      observer?.disconnect();
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
      className="inline-flex min-h-11 min-w-11 shrink-0 items-center justify-center rounded-lg text-secondary hover:bg-hover hover:text-primary"
      aria-label="Cerrar"
    >
      <X className="h-4 w-4" strokeWidth={1.75} aria-hidden />
    </button>
  );

  if (surface === "sheet") {
    return createPortal(
      <div className="fixed inset-0 z-50" data-evidence-surface="sheet">
        <div aria-hidden="true" className="absolute inset-0 bg-background/70" onClick={onDismiss} />
        <div
          ref={panelRef}
          id={dialogId}
          role="dialog"
          aria-modal="true"
          aria-labelledby={titleId}
          tabIndex={-1}
          onKeyDown={onPanelKeyDown}
          className="evidence-sheet absolute inset-x-0 bottom-0 flex max-h-[min(85dvh,calc(100dvh-env(safe-area-inset-top)))] w-full min-w-0 flex-col outline-none"
        >
          <div className="flex items-center justify-between gap-3 border-b border-border px-5 py-3">
            <h2 id={titleId} className="font-heading text-lg font-semibold text-primary">
              {title}
            </h2>
            {closeButton}
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4 pb-[max(1.25rem,env(safe-area-inset-bottom))]">
            {children}
          </div>
        </div>
      </div>,
      document.body,
    );
  }

  return createPortal(
    <>
      {bridge ? (
        <div
          aria-hidden="true"
          data-evidence-bridge="true"
          onMouseEnter={onContentEnter}
          className="fixed z-40"
          style={{ top: bridge.top, left: bridge.left, width: bridge.width, height: bridge.height }}
        />
      ) : null}
      <div
        ref={panelRef}
        id={dialogId}
        role="dialog"
        aria-modal="false"
        aria-labelledby={titleId}
        tabIndex={-1}
        data-evidence-surface="popover"
        data-side="right"
        onMouseEnter={onContentEnter}
        onMouseLeave={onContentLeave}
        onKeyDown={onPanelKeyDown}
        className="evidence-popover fixed z-50 outline-none"
      >
        <div className="-mr-2 -mt-2 mb-1 flex items-start justify-end">
          <h2 id={titleId} className="sr-only">
            {title}
          </h2>
          {closeButton}
        </div>
        {children}
      </div>
    </>,
    document.body,
  );
}
