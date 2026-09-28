import type { NextConfig } from "next";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

function loadSharedAppSecret() {
  if (process.env.APP_SECRET?.trim()) return;
  for (const file of [resolve(process.cwd(), "../.env"), resolve(process.cwd(), ".env")]) {
    try {
      for (const line of readFileSync(file, "utf8").split(/\r?\n/)) {
        if (!line.startsWith("APP_SECRET=")) continue;
        const value = line.slice("APP_SECRET=".length).trim().replace(/^['"]|['"]$/g, "");
        if (value) process.env.APP_SECRET = value;
        return;
      }
    } catch {
      // Sin el archivo, la sesión usa el mismo default que la API de desarrollo.
    }
  }
}

loadSharedAppSecret();

const apiUrl = process.env.API_URL ?? (process.env.VERCEL ? "" : "http://localhost:8000");

const nextConfig: NextConfig = {
  images: {
    remotePatterns: [
      { protocol: "https", hostname: "**" },
      { protocol: "http", hostname: "**" },
    ],
  },
  async rewrites() {
    if (!apiUrl) return [];
    return [
      {
        source: "/api/v1/:path*",
        destination: `${apiUrl}/api/v1/:path*`,
      },
    ];
  },
  async headers() {
    const noIndex = [{ key: "X-Robots-Tag", value: "noindex, nofollow" }];
    return [
      {
        source: "/seguimiento/:path*",
        headers: [
          { key: "Cache-Control", value: "private, no-store" },
          { key: "Referrer-Policy", value: "no-referrer" },
          { key: "X-Robots-Tag", value: "noindex, nofollow" },
        ],
      },
      { source: "/admin", headers: noIndex },
      { source: "/admin/:path*", headers: noIndex },
      { source: "/entrar", headers: noIndex },
      { source: "/registro", headers: noIndex },
      { source: "/onboarding", headers: noIndex },
      { source: "/dev/:path*", headers: noIndex },
    ];
  },
};

export default nextConfig;
