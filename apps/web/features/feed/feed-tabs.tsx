"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";

const TABS = [
  { id: "para-vos", label: "Para vos", href: "/" },
  { id: "local", label: "Local", href: "/?vista=local" },
  { id: "argentina", label: "Argentina", href: "/?vista=argentina" },
] as const;

export type HomeVista = "para-vos" | "local" | "argentina";

export function parseVista(value: string | null): HomeVista {
  if (value === "local" || value === "argentina") return value;
  return "para-vos";
}

export function FeedTabs() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const vista = pathname === "/" ? parseVista(searchParams.get("vista")) : null;

  return (
    <nav aria-label="Filtros del feed" className="flex border-b border-border">
      {TABS.map((tab) => {
        const active = vista === tab.id;
        return (
          <Link
            key={tab.id}
            href={tab.href}
            className={`relative flex-1 py-3 text-center font-heading text-sm ${
              active ? "text-primary" : "text-secondary hover:text-primary"
            }`}
            aria-current={active ? "page" : undefined}
          >
            {tab.label}
            {active ? <span className="absolute inset-x-6 bottom-0 h-px bg-accent-petrol" /> : null}
          </Link>
        );
      })}
    </nav>
  );
}
