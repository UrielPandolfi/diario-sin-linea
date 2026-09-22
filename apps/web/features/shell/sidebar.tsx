"use client";

import { BrandMark } from "@/features/shell/brand-mark";
import { navIsActive, NAV_ITEMS, type NavItem } from "@/lib/nav";
import {
  Bell,
  Bookmark,
  CircleHelp,
  House,
  Mail,
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

function NavLink({
  href,
  label,
  icon: Icon,
  active,
}: {
  href: string;
  label: string;
  icon: LucideIcon;
  active: boolean;
}) {
  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      title={label}
      className={`flex items-center gap-3 rounded-lg px-2.5 py-2 font-sans text-[14px] transition-colors ${
        active ? "bg-hover text-primary" : "text-secondary hover:bg-hover/70 hover:text-primary"
      }`}
    >
      <Icon className="h-[18px] w-[18px] shrink-0" strokeWidth={active ? 2 : 1.7} aria-hidden />
      <span className="hidden lg:inline">{label}</span>
    </Link>
  );
}

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="sticky top-0 hidden h-screen w-16 shrink-0 flex-col border-r border-border bg-nav md:flex lg:w-[15.25rem]">
      <div className="flex h-full flex-col px-2 py-5 lg:px-3.5">
        <Link href="/" className="mb-8 flex items-center gap-2.5 px-2 text-primary">
          <BrandMark className="h-8 w-8 shrink-0" />
          <span className="hidden font-heading text-[15px] font-semibold tracking-[0.04em] lg:inline">
            Sin Línea
          </span>
        </Link>
        <nav aria-label="Principal" className="flex flex-1 flex-col gap-0.5">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.href}
              href={item.href}
              label={item.label}
              icon={ICONS[item.icon]}
              active={navIsActive(item.href, pathname)}
            />
          ))}
        </nav>
        <nav aria-label="Acerca de" className="mt-auto border-t border-border pt-3">
          <NavLink
            href="/contacto"
            label="Contacto"
            icon={Mail}
            active={navIsActive("/contacto", pathname)}
          />
          <NavLink
            href="/como-funciona"
            label="Cómo funciona"
            icon={CircleHelp}
            active={navIsActive("/como-funciona", pathname)}
          />
        </nav>
      </div>
    </aside>
  );
}
