import { FeedList } from "@/features/feed/feed-list";
import { SectionFrame } from "@/features/shell/section-frame";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Guardados",
  robots: { index: false, follow: false },
};

export default function SavedPage() {
  return (
    <SectionFrame now nearby>
      <header className="border-b border-border bg-background/80 px-4 py-4 backdrop-blur-md md:px-6">
        <h1 className="font-heading text-2xl font-semibold text-primary">Guardados</h1>
      </header>
      <FeedList kind="saved" emptyTitle="Todavía no guardaste noticias" />
    </SectionFrame>
  );
}
