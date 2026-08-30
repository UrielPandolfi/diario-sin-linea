"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ReactNode } from "react";
import { ThemeToggle } from "@/components/theme-toggle";

const NAV = [
  { href: "/admin", label: "Tablero" },
  { href: "/admin/sources", label: "Fuentes" },
  { href: "/admin/events", label: "Sucesos" },
  { href: "/admin/published", label: "Publicadas" },
];

function navIsActive(href: string, pathname: string): boolean {
  if (href === "/admin") return pathname === "/admin";
  return pathname === href || pathname.startsWith(`${href}/`);
}

export default function AdminLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  if (pathname === "/admin/login") {
    return <>{children}</>;
  }

  async function logout() {
    await fetch("/api/v1/admin/logout", { method: "POST", credentials: "include" });
    window.location.href = "/admin/login";
  }

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b border-border bg-surface">
        <div className="mx-auto flex max-w-5xl items-center justify-between gap-4 px-6 py-4">
          <div>
            <p className="font-heading text-xs uppercase tracking-[0.18em] text-accent-ochre">Sin Línea</p>
            <p className="font-heading text-lg text-primary">Redacción interna</p>
          </div>
          <nav className="flex flex-wrap items-center gap-3 font-sans text-sm">
            {NAV.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className={navIsActive(item.href, pathname) ? "text-primary" : "text-secondary"}
              >
                {item.label}
              </Link>
            ))}
            <ThemeToggle />
            <button type="button" onClick={() => void logout()} className="text-secondary">
              Salir
            </button>
          </nav>
        </div>
      </header>
      <div className="mx-auto max-w-5xl px-6 py-8">{children}</div>
    </div>
  );
}
