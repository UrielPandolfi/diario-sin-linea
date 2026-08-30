"use client";

import { navIsActive, NAV_ITEMS, type NavItem } from "@/lib/nav";
import { House, MapPin, Radio, Search, User, type LucideIcon } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

const MOBILE_ICONS: Record<string, LucideIcon> = {
  home: House,
  live: Radio,
  search: Search,
  local: MapPin,
  profile: User,
};

export function MobileNav() {
  const pathname = usePathname();
  const items = NAV_ITEMS.filter((item: NavItem) => item.mobile);

  return (
    <nav
      aria-label="Navegación inferior"
      className="fixed inset-x-0 bottom-0 z-30 border-t border-border bg-background md:hidden"
    >
      <ul className="grid grid-cols-5">
        {items.map((item) => {
          const Icon = MOBILE_ICONS[item.icon];
          const active = navIsActive(item.href, pathname);
          return (
            <li key={item.href}>
              <Link
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={`flex flex-col items-center gap-1 py-2.5 font-sans text-[10px] ${
                  active ? "text-primary" : "text-secondary"
                }`}
              >
                {Icon ? <Icon className="h-5 w-5" strokeWidth={active ? 2.2 : 1.75} aria-hidden /> : null}
                <span>{item.label}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
