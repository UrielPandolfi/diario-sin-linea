export const THEME_COOKIE = "sl_theme";
export const THEME_STORAGE_KEY = "sl-theme";
export const DEFAULT_THEME = "light" as const;

export type Theme = "light" | "dark";

export function parseTheme(value: string | null | undefined): Theme | null {
  return value === "light" || value === "dark" ? value : null;
}

export function resolveTheme(stored: string | null | undefined): Theme {
  return parseTheme(stored) ?? DEFAULT_THEME;
}

export function themeCookie(theme: Theme): string {
  return `${THEME_COOKIE}=${theme}; Path=/; Max-Age=31536000; SameSite=Lax`;
}

export const THEME_BOOTSTRAP_SCRIPT = `(function(){try{var k=${JSON.stringify(THEME_STORAGE_KEY)};var t=localStorage.getItem(k);if(t==="light"||t==="dark"){document.documentElement.setAttribute("data-theme",t);}else if(!document.documentElement.getAttribute("data-theme")){document.documentElement.setAttribute("data-theme",${JSON.stringify(DEFAULT_THEME)});}}catch(e){document.documentElement.setAttribute("data-theme",${JSON.stringify(DEFAULT_THEME)});}})();`;
