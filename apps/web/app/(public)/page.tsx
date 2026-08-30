import { HomeFeed } from "@/features/feed/home-feed";
import type { Metadata } from "next";
import { Suspense } from "react";

export const metadata: Metadata = {
  title: "Inicio",
};

export default function HomePage() {
  return (
    <Suspense fallback={<div className="h-40 animate-pulse bg-surface" />}>
      <HomeFeed />
    </Suspense>
  );
}
