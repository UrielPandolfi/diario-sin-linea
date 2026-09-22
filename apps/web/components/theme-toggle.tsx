"use client";

import { useInitialTheme } from "@/components/theme-provider";
import { Moon, Sun } from "lucide-react";
import { useEffect, useState } from "react";
import { THEME_STORAGE_KEY, themeCookie, type Theme } from "@/lib/theme";

function readTheme(): Theme {
  if (typeof document === "undefined") return "light";
  const current = document.documentElement.getAttribute("data-theme");
  return current === "dark" ? "dark" : "light";
}

function persistTheme(next: Theme) {
  document.documentElement.setAttribute("data-theme", next);
  try {
    localStorage.setItem(THEME_STORAGE_KEY, next);
  } catch {
    /* private mode */
  }
  document.cookie = themeCookie(next);
}

export function ThemeToggle({ variant = "icon" }: { variant?: "icon" | "labeled" }) {
  const initialTheme = useInitialTheme();
  const [theme, setTheme] = useState<Theme>(initialTheme);

  useEffect(() => {
    setTheme(readTheme());
  }, []);

  function toggle() {
    const next: Theme = theme === "dark" ? "light" : "dark";
    persistTheme(next);
    setTheme(next);
  }

  const nextLabel = theme === "dark" ? "Cambiar a tema claro" : "Cambiar a tema oscuro";
  const stateLabel = theme === "dark" ? "Tema oscuro" : "Tema claro";

  if (variant === "labeled") {
    return (
      <button
        type="button"
        onClick={toggle}
        aria-pressed={theme === "dark"}
        aria-label={`${nextLabel}. ${stateLabel} activo.`}
        className="inline-flex items-center gap-2 rounded-lg border border-border bg-surface px-3 py-2 font-sans text-sm text-secondary transition-colors hover:bg-hover hover:text-primary"
      >
        {theme === "dark" ? <Sun className="h-4 w-4" aria-hidden /> : <Moon className="h-4 w-4" aria-hidden />}
        {theme === "dark" ? "Tema claro" : "Tema oscuro"}
      </button>
    );
  }

  return (
    <button
      type="button"
      onClick={toggle}
      aria-pressed={theme === "dark"}
      aria-label={`${nextLabel}. ${stateLabel} activo.`}
      title={nextLabel}
      className="inline-flex h-11 w-11 items-center justify-center rounded-lg text-secondary transition-colors hover:bg-hover hover:text-primary"
    >
      {theme === "dark" ? <Sun className="h-4 w-4" strokeWidth={1.75} aria-hidden /> : <Moon className="h-4 w-4" strokeWidth={1.75} aria-hidden />}
    </button>
  );
}
