"use client";

import { SignOutButton } from "@/features/auth/sign-out-button";
import { navIsActive, NAV_ITEMS, type NavItem } from "@/lib/nav";
import {
  Bell,
  Bookmark,
  CircleHelp,
  Ellipsis,
  Eye,
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
import { useEffect, useId, useRef, useState } from "react";

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

const PRIMARY_ITEMS = NAV_ITEMS.filter((item) => item.href !== "/perfil");
const PROFILE_ITEM = NAV_ITEMS.find((item) => item.href === "/perfil");

const MORE_LINKS: { href: string; label: string; icon: LucideIcon }[] = [
  { href: "/transparencia", label: "Transparencia", icon: Eye },
  { href: "/como-funciona", label: "Cómo funciona", icon: CircleHelp },
  { href: "/contacto", label: "Contacto", icon: Mail },
];

function NavLink({
  href,
  label,
  icon: Icon,
  active,
  showLabel = false,
  onClick,
}: {
  href: string;
  label: string;
  icon: LucideIcon;
  active: boolean;
  showLabel?: boolean;
  onClick?: () => void;
}) {
  return (
    <Link
      href={href}
      role={showLabel ? "menuitem" : undefined}
      aria-current={active ? "page" : undefined}
      title={label}
      onClick={onClick}
      className={`sl-nav-link flex items-center gap-3 rounded-lg px-2.5 py-2 font-sans text-[14px] ${
        active ? "text-primary" : "text-secondary hover:bg-hover/70 hover:text-primary"
      }`}
    >
      <Icon className="h-[18px] w-[18px] shrink-0" strokeWidth={active ? 2 : 1.7} aria-hidden />
      <span className={showLabel ? undefined : "hidden lg:inline"}>{label}</span>
    </Link>
  );
}

function MoreMenu({ pathname }: { pathname: string }) {
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState({ top: 0, left: 0 });
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const unlistenRef = useRef<(() => void) | null>(null);
  const menuId = useId();
  const sectionActive = MORE_LINKS.some((item) => navIsActive(item.href, pathname));

  function place() {
    const rect = buttonRef.current?.getBoundingClientRect();
    if (!rect) return;
    const width = 224;
    const left = Math.min(rect.right + 8, window.innerWidth - width - 8);
    setPosition({ top: rect.top, left: Math.max(8, left) });
  }

  function unlisten() {
    unlistenRef.current?.();
    unlistenRef.current = null;
  }

  function closeMenu() {
    unlisten();
    setOpen(false);
  }

  function listen() {
    unlisten();
    function onPointerDown(event: Event) {
      const target = event.target;
      if (!(target instanceof Node) || !rootRef.current?.contains(target)) closeMenu();
    }
    function onKey(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      closeMenu();
      buttonRef.current?.focus();
    }
    document.addEventListener("pointerdown", onPointerDown, true);
    document.addEventListener("mousedown", onPointerDown, true);
    document.addEventListener("keydown", onKey);
    window.addEventListener("resize", place);
    unlistenRef.current = () => {
      document.removeEventListener("pointerdown", onPointerDown, true);
      document.removeEventListener("mousedown", onPointerDown, true);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("resize", place);
    };
  }

  const skipPathReset = useRef(true);
  useEffect(() => {
    if (skipPathReset.current) {
      skipPathReset.current = false;
      return;
    }
    closeMenu();
  }, [pathname]);

  useEffect(() => () => unlisten(), []);

  return (
    <div ref={rootRef}>
      <button
        ref={buttonRef}
        type="button"
        aria-expanded={open}
        aria-haspopup="menu"
        aria-controls={menuId}
        aria-label="Más"
        title="Más"
        data-current={open || sectionActive ? "true" : undefined}
        onClick={() => {
          if (open) {
            closeMenu();
            return;
          }
          place();
          listen();
          setOpen(true);
        }}
        className={`sl-nav-link flex w-full items-center gap-3 rounded-lg px-2.5 py-2 font-sans text-[14px] ${
          open || sectionActive ? "text-primary" : "text-secondary hover:bg-hover/70 hover:text-primary"
        }`}
      >
        <Ellipsis className="h-[18px] w-[18px] shrink-0" strokeWidth={open || sectionActive ? 2 : 1.7} aria-hidden />
        <span className="hidden lg:inline">Más</span>
      </button>
      {open ? (
        <div
          id={menuId}
          role="menu"
          aria-label="Más"
          style={{ top: position.top, left: position.left }}
          className="sl-panel fixed z-40 flex w-56 flex-col gap-0.5 rounded-xl border border-border bg-nav p-1.5 shadow-[0_10px_24px_var(--shadow)]"
        >
          {MORE_LINKS.map((item) => (
            <NavLink
              key={item.href}
              href={item.href}
              label={item.label}
              icon={item.icon}
              active={navIsActive(item.href, pathname)}
              showLabel
              onClick={closeMenu}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}

export function Sidebar({ authenticated = false }: { authenticated?: boolean }) {
  const pathname = usePathname();

  return (
    <aside className="sl-nav-bleed sticky top-0 z-20 hidden h-screen w-16 shrink-0 flex-col border-r border-border bg-nav md:flex lg:w-[15.25rem]">
      <div className="flex h-full flex-col px-2 py-5 lg:px-3.5">
        <Link href="/" className="mb-8 flex w-full items-center px-1" aria-label="Sin Línea">
          <span className="sl-logo hidden w-full lg:block" />
          <img src="/favicon.png" alt="" className="h-8 w-8 lg:hidden" />
        </Link>
        <nav aria-label="Principal" className="flex flex-1 flex-col gap-0.5">
          {PRIMARY_ITEMS.map((item) => (
            <NavLink
              key={item.href}
              href={item.href}
              label={item.label}
              icon={ICONS[item.icon]}
              active={navIsActive(item.href, pathname)}
            />
          ))}
          <MoreMenu pathname={pathname} />
        </nav>
        <nav aria-label="Cuenta" className="mt-auto border-t border-border pt-3">
          {authenticated ? <SignOutButton className="mt-1 w-full" /> : null}
          {PROFILE_ITEM ? (
            <NavLink
              href={PROFILE_ITEM.href}
              label={PROFILE_ITEM.label}
              icon={ICONS[PROFILE_ITEM.icon]}
              active={navIsActive(PROFILE_ITEM.href, pathname)}
            />
          ) : null}
        </nav>
      </div>
    </aside>
  );
}
