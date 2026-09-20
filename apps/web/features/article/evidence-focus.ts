export const EVIDENCE_FOCUSABLE =
  'a[href], button:not([disabled]), summary, textarea, input, select, [tabindex]:not([tabindex="-1"])';

export function focusableElements(root: HTMLElement | null): HTMLElement[] {
  if (!root) return [];
  return Array.from(root.querySelectorAll<HTMLElement>(EVIDENCE_FOCUSABLE)).filter((node) => {
    if (node.hasAttribute("disabled") || node.getAttribute("aria-hidden") === "true") return false;
    if (node.hidden || node.getAttribute("hidden") !== null) return false;
    return true;
  });
}
