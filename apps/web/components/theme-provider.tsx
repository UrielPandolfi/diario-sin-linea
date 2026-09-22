"use client";

import { createContext, useContext, type ReactNode } from "react";
import type { Theme } from "@/lib/theme";

const InitialThemeContext = createContext<Theme>("light");

export function InitialThemeProvider({ theme, children }: { theme: Theme; children: ReactNode }) {
  return <InitialThemeContext.Provider value={theme}>{children}</InitialThemeContext.Provider>;
}

export function useInitialTheme(): Theme {
  return useContext(InitialThemeContext);
}
