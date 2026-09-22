import type { Metadata } from "next";
import type { ReactNode } from "react";
import { cookies } from "next/headers";
import { Inter, Newsreader } from "next/font/google";
import { InitialThemeProvider } from "@/components/theme-provider";
import { ThemeScript } from "@/components/theme-script";
import { JsonLd } from "@/lib/seo/json-ld-script";
import { organizationJsonLd } from "@/lib/seo/json-ld";
import { rootMetadata } from "@/lib/seo/metadata";
import { getSiteUrl, isIndexableDeploy } from "@/lib/seo/site-url";
import { THEME_COOKIE, resolveTheme } from "@/lib/theme";
import "./globals.css";

const newsreader = Newsreader({
  subsets: ["latin", "latin-ext"],
  weight: ["400", "500", "600", "700"],
  style: ["normal", "italic"],
  variable: "--font-heading",
  display: "swap",
  adjustFontFallback: true,
});

const inter = Inter({
  subsets: ["latin", "latin-ext"],
  weight: ["400", "500", "600"],
  variable: "--font-sans",
  display: "swap",
});

export function generateMetadata(): Metadata {
  return rootMetadata(getSiteUrl(), isIndexableDeploy());
}

export default async function RootLayout({ children }: { children: ReactNode }) {
  const origin = getSiteUrl();
  const cookieStore = await cookies();
  const theme = resolveTheme(cookieStore.get(THEME_COOKIE)?.value);
  return (
    <html
      lang="es-AR"
      data-theme={theme}
      className={`${newsreader.variable} ${inter.variable}`}
      suppressHydrationWarning
    >
      <head>
        <ThemeScript />
      </head>
      <body className="min-h-screen bg-background font-sans text-primary antialiased">
        <JsonLd data={organizationJsonLd(origin)} />
        <InitialThemeProvider theme={theme}>{children}</InitialThemeProvider>
      </body>
    </html>
  );
}
