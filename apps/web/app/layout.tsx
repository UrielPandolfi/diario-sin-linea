import type { Metadata } from "next";
import type { ReactNode } from "react";
import { Inter, Manrope } from "next/font/google";
import { JsonLd } from "@/lib/seo/json-ld-script";
import { organizationJsonLd } from "@/lib/seo/json-ld";
import { rootMetadata } from "@/lib/seo/metadata";
import { getSiteUrl, isIndexableDeploy } from "@/lib/seo/site-url";
import "./globals.css";

const manrope = Manrope({
  subsets: ["latin", "latin-ext"],
  weight: ["500", "600"],
  variable: "--font-heading",
  display: "swap",
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

export default function RootLayout({ children }: { children: ReactNode }) {
  const origin = getSiteUrl();
  return (
    <html lang="es-AR" data-theme="dark" className={`${manrope.variable} ${inter.variable}`}>
      <body className="min-h-screen bg-background font-sans text-primary antialiased">
        <JsonLd data={organizationJsonLd(origin)} />
        {children}
      </body>
    </html>
  );
}
