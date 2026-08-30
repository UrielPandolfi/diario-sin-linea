export type NavItem = {
  href: string;
  label: string;
  icon: "home" | "live" | "search" | "following" | "alerts" | "local" | "saved" | "profile";
  mobile?: boolean;
};

export const NAV_ITEMS: NavItem[] = [
  { href: "/", label: "Inicio", icon: "home", mobile: true },
  { href: "/en-vivo", label: "En vivo", icon: "live", mobile: true },
  { href: "/buscar", label: "Buscar", icon: "search", mobile: true },
  { href: "/seguidos", label: "Seguidos", icon: "following" },
  { href: "/notificaciones", label: "Notificaciones", icon: "alerts" },
  { href: "/local", label: "Local", icon: "local", mobile: true },
  { href: "/guardados", label: "Guardados", icon: "saved" },
  { href: "/perfil", label: "Perfil", icon: "profile", mobile: true },
];

export function navIsActive(href: string, pathname: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}
