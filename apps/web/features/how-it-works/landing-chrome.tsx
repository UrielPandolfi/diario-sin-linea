"use client";

import { BrandMark } from "@/features/shell/brand-mark";
import Link from "next/link";
import { useEffect, useRef } from "react";

const ANCHORS = [
  { href: "#proceso", label: "El proceso" },
  { href: "#estados", label: "Estados" },
  { href: "#evidencia", label: "Evidencia" },
  { href: "#principios", label: "Principios" },
] as const;

export function LandingHeader() {
  const barRef = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    const update = () => {
      const bar = barRef.current;
      if (!bar) return;
      const scrollable = document.documentElement.scrollHeight - window.innerHeight;
      const progress = scrollable > 0 ? Math.min(window.scrollY / scrollable, 1) : 0;
      bar.style.transform = `scaleX(${progress})`;
    };

    update();
    window.addEventListener("scroll", update, { passive: true });
    window.addEventListener("resize", update);
    return () => {
      window.removeEventListener("scroll", update);
      window.removeEventListener("resize", update);
    };
  }, []);

  return (
    <header className="sticky top-0 z-40 border-b border-border bg-background/85 backdrop-blur-sm">
      <div className="mx-auto flex h-14 max-w-[1240px] items-center justify-between gap-4 px-5 md:h-16 md:px-8">
        <Link href="/" className="flex items-center gap-2.5 text-accent-ochre">
          <BrandMark className="h-7 w-7 shrink-0" />
          <span className="font-heading text-[13px] font-medium uppercase tracking-[0.16em] text-primary">
            Sin Línea
          </span>
        </Link>

        <nav aria-label="Secciones" className="hidden items-center gap-7 lg:flex">
          {ANCHORS.map((anchor) => (
            <a
              key={anchor.href}
              href={anchor.href}
              className="font-sans text-[13px] text-secondary transition-colors hover:text-primary"
            >
              {anchor.label}
            </a>
          ))}
        </nav>

        <Link
          href="/"
          className="shrink-0 border border-border px-3.5 py-2 font-sans text-[13px] font-medium text-primary transition-colors hover:border-accent-petrol hover:text-accent-petrol md:px-4"
        >
          Ver las noticias
        </Link>
      </div>
      <span
        ref={barRef}
        aria-hidden
        className="absolute inset-x-0 bottom-0 h-px origin-left scale-x-0 bg-accent-petrol"
      />
    </header>
  );
}

export function LandingFooter() {
  return (
    <footer className="border-t border-border px-5 py-10 md:px-8 md:py-14">
      <div className="mx-auto flex max-w-[1240px] flex-col gap-8 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="font-heading text-lg font-medium uppercase tracking-[0.18em] text-primary">Sin Línea</p>
          <p className="mt-2 font-sans text-sm text-secondary">Los hechos. El criterio es tuyo.</p>
        </div>
        <nav aria-label="Sitio" className="flex flex-wrap gap-x-6 gap-y-2 font-sans text-sm text-secondary">
          <Link href="/" className="text-secondary hover:text-primary">
            Inicio
          </Link>
          <Link href="/en-vivo" className="text-secondary hover:text-primary">
            En vivo
          </Link>
          <Link href="/contacto" className="text-secondary hover:text-primary">
            Contacto
          </Link>
        </nav>
      </div>
    </footer>
  );
}
