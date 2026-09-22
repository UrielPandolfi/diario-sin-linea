import { SearchView } from "@/features/search/search-view";
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
    <div className="mx-auto min-h-screen max-w-measure">
      <header className="sticky top-0 z-10 border-b border-border bg-background/95 px-4 py-3 md:px-6">
        <h1 className="font-heading text-2xl font-semibold text-primary">Buscar</h1>
      </header>
      <SearchView />
    </div>
  );
}
