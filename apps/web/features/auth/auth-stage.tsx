"use client";

import { useEffect, useRef, type ReactNode } from "react";

export function AuthStage({ children }: { children: ReactNode }) {
  const stageRef = useRef<HTMLElement>(null);
  const glow = useRef({ x: 0.34, y: 0.46 });
  const glowTarget = useRef({ x: 0.34, y: 0.46 });

  useEffect(() => {
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    if (media.matches) return;
    let frame = 0;
    let running = true;
    const onMove = (event: globalThis.PointerEvent) => {
      const width = window.innerWidth;
      const height = window.innerHeight;
      if (width === 0 || height === 0) return;
      glowTarget.current.x = Math.min(1, Math.max(0, event.clientX / width));
      glowTarget.current.y = Math.min(1, Math.max(0, event.clientY / height));
    };
    const tick = () => {
      if (!running) return;
      const stage = stageRef.current;
      if (stage) {
        glow.current.x += (glowTarget.current.x - glow.current.x) * 0.08;
        glow.current.y += (glowTarget.current.y - glow.current.y) * 0.08;
        stage.style.setProperty("--auth-x", `${(glow.current.x * 100).toFixed(2)}%`);
        stage.style.setProperty("--auth-y", `${(glow.current.y * 100).toFixed(2)}%`);
      }
      frame = window.requestAnimationFrame(tick);
    };
    window.addEventListener("pointermove", onMove);
    frame = window.requestAnimationFrame(tick);
    return () => {
      running = false;
      window.removeEventListener("pointermove", onMove);
      window.cancelAnimationFrame(frame);
    };
  }, []);

  return (
    <main className="sl-enter grid min-h-screen bg-background lg:grid-cols-2">
      <section
        ref={stageRef}
        className="sl-auth-stage relative flex min-h-[46vh] flex-col justify-between overflow-hidden px-8 py-10 md:px-14 md:py-16 lg:min-h-screen lg:px-16 xl:px-24"
      >
        <div className="sl-auth-lines" aria-hidden>
          <span style={{ top: "16%" }} />
          <span style={{ top: "34%" }} />
          <span className="is-cursor" style={{ top: "var(--auth-y)" }} />
          <span data-warm="" style={{ top: "58%" }} />
          <span data-warm="" style={{ top: "76%" }} />
        </div>
        <span className="sl-logo relative z-10 h-9 w-[12.8rem]" role="img" aria-label="Sin Línea" />
        <div className="relative z-10 max-w-md py-16 lg:py-0">
          <h1 className="font-heading text-4xl font-semibold leading-[1.08] tracking-tight text-primary md:text-5xl">
            Entendé qué está pasando.
          </h1>
          <p className="mt-5 max-w-sm font-sans text-base leading-relaxed text-secondary">
            Información basada en hechos, fuentes y evidencia.
          </p>
        </div>
        <p className="relative z-10 hidden font-sans text-xs text-muted lg:block">Medio informativo centrado en sucesos.</p>
      </section>

      <section className="flex flex-col justify-center border-t border-border bg-background px-8 py-12 lg:border-l lg:border-t-0 lg:px-14 xl:px-20">
        {children}
      </section>
    </main>
  );
}
