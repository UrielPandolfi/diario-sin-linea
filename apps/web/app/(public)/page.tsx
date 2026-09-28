import { HomeFeed } from "@/features/feed/home-feed";
import { readerFromCookie } from "@/lib/auth/session";
import { JsonLd } from "@/lib/seo/json-ld-script";
import { webSiteJsonLd } from "@/lib/seo/json-ld";
import { SITE_DESCRIPTION, SITE_NAME } from "@/lib/seo/constants";
import { getSiteUrl } from "@/lib/seo/site-url";
import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { Suspense } from "react";

export const metadata: Metadata = {
  title: { absolute: SITE_NAME },
  description: SITE_DESCRIPTION,
  alternates: { canonical: "/" },
  robots: { index: false, follow: false },
};

export const dynamic = "force-dynamic";

function homeNext(params: Record<string, string | string[] | undefined>): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (typeof value === "string") query.append(key, value);
    else if (Array.isArray(value)) {
      for (const item of value) query.append(key, item);
    }
  }
  const encoded = query.toString();
  return encoded ? `/?${encoded}` : "/";
}

export default async function HomePage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  if (!(await readerFromCookie())) {
    redirect(`/entrar?next=${encodeURIComponent(homeNext(params))}`);
  }
  return (
    <>
      <JsonLd data={webSiteJsonLd(getSiteUrl())} />
      <Suspense fallback={<div className="h-40 animate-pulse bg-surface" />}>
        <HomeFeed />
      </Suspense>
    </>
  );
}
