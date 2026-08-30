"use client";

import { BrandMark } from "@/features/shell/brand-mark";
import { navIsActive, NAV_ITEMS, type NavItem } from "@/lib/nav";
import {
  Bell,
  Bookmark,
  House,
  MapPin,
  Radio,
  Search,
  User,
  Users,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

const ICONS: Record<NavItem["icon"], LucideIcon> = {
  home: House,
  live: Radio,
  search: Search,
  following: Users,
  alerts: Bell,
  local: MapPin,
  saved: Bookmark,
  profile: User,
};

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="sticky top-0 hidden h-screen w-16 shrink-0 flex-col border-r border-border bg-background md:flex lg:w-56">
      <div className="flex h-full flex-col px-2 py-5 lg:px-4">
        <Link href="/" className="mb-8 flex items-center gap-2 px-2 text-accent-ochre">
          <BrandMark className="h-8 w-8 shrink-0" />
          <span className="hidden font-heading text-sm font-medium uppercase tracking-[0.16em] lg:inline">
            Sin Línea
          </span>
        </Link>
        <nav aria-label="Principal" className="flex flex-1 flex-col gap-1">
          {NAV_ITEMS.map((item) => {
            const Icon = ICONS[item.icon];
            const active = navIsActive(item.href, pathname);
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={active ? "page" : undefined}
                title={item.label}
                className={`flex items-center gap-3 px-2 py-2.5 font-sans text-sm transition-colors ${
                  active ? "bg-hover text-primary" : "text-secondary hover:bg-hover hover:text-primary"
                }`}
              >
                <Icon className="h-[18px] w-[18px] shrink-0" strokeWidth={active ? 2.2 : 1.75} aria-hidden />
                <span className="hidden lg:inline">{item.label}</span>
              </Link>
            );
          })}
        </nav>
      </div>
    </aside>
  );
}
