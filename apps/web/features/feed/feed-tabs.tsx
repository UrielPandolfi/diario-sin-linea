"use client";

import { parseVista, type HomeVista } from "@/lib/feed/vista";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";

const TABS = [
  { id: "principal", label: "Principal", href: "/" },
  { id: "ultimas", label: "Últimas", href: "/?vista=ultimas" },
] as const;

export type { HomeVista };
export { parseVista };

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
            className={`relative flex-1 py-3 text-center font-sans text-sm ${
              active ? "font-medium text-primary" : "text-secondary hover:text-primary"
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
