import { HomeFeed } from "@/features/feed/home-feed";
import { JsonLd } from "@/lib/seo/json-ld-script";
import { webSiteJsonLd } from "@/lib/seo/json-ld";
import { SITE_DESCRIPTION, SITE_NAME } from "@/lib/seo/constants";
import { getSiteUrl } from "@/lib/seo/site-url";
import type { Metadata } from "next";
import { Suspense } from "react";

export const metadata: Metadata = {
  title: { absolute: SITE_NAME },
  description: SITE_DESCRIPTION,
  alternates: { canonical: "/" },
};

export default function HomePage() {
  return (
    <>
      <JsonLd data={webSiteJsonLd(getSiteUrl())} />
      <Suspense fallback={<div className="h-40 animate-pulse bg-surface" />}>
        <HomeFeed />
      </Suspense>
    </>
  );
}
