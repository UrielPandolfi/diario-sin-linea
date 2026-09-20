"use client";

import { evidenceSurface } from "./claim-popover-copy";
import { useLayoutEffect, useState } from "react";

const FINE_HOVER = "(hover: hover) and (pointer: fine)";

export function useEvidenceSurface(): "popover" | "sheet" | null {
  const [surface, setSurface] = useState<"popover" | "sheet" | null>(null);

  useLayoutEffect(() => {
    const media = window.matchMedia(FINE_HOVER);
    function update() {
      const next = evidenceSurface({
        hoverFine: media.matches,
        viewportWidth: window.innerWidth,
      });
      setSurface((current) => (current === next ? current : next));
    }
    update();
    media.addEventListener("change", update);
    window.addEventListener("resize", update);
    return () => {
      media.removeEventListener("change", update);
      window.removeEventListener("resize", update);
    };
  }, []);

  return surface;
}
