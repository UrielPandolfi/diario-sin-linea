import type { Metadata } from "next";
import type { ReactNode } from "react";
import { cookies, headers } from "next/headers";
import { Inter, Newsreader } from "next/font/google";
import { PlausibleAnalytics } from "@/components/plausible-analytics";
import { InitialThemeProvider } from "@/components/theme-provider";
import { ThemeScript } from "@/components/theme-script";
import { isPlausibleEnabled } from "@/lib/analytics/plausible";
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
  const headerStore = await headers();
  const cookieStore = await cookies();
  const theme = resolveTheme(cookieStore.get(THEME_COOKIE)?.value);
  const analytics = isPlausibleEnabled(
    process.env,
    headerStore.get("x-forwarded-host") ?? headerStore.get("host"),
  );
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
        <PlausibleAnalytics enabled={analytics} />
        <JsonLd data={organizationJsonLd(origin)} />
        <InitialThemeProvider theme={theme}>{children}</InitialThemeProvider>
      </body>
    </html>
  );
}
