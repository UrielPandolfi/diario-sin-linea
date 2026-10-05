import { SearchView } from "@/features/search/search-view";
import { SectionFrame } from "@/features/shell/section-frame";
import { NO_INDEX_FOLLOW } from "@/lib/seo/metadata";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Buscar",
  description: "Buscá sucesos publicados en Sin Línea.",
  robots: NO_INDEX_FOLLOW,
  alternates: { canonical: "/buscar" },
};

export default function SearchPage() {
  return (
    <SectionFrame now nearby>
      <header className="sticky top-0 z-10 border-b border-border bg-background px-4 py-3 md:px-6">
        <h1 className="font-heading text-2xl font-semibold text-primary">Buscar</h1>
      </header>
      <SearchView />
    </SectionFrame>
  );
}
