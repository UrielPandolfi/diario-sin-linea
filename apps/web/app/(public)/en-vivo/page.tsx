import { LiveTimeline } from "@/features/live/live-timeline";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "En vivo",
  description: "Sucesos publicados, ordenados por la última actualización.",
  alternates: { canonical: "/en-vivo" },
};

export default function LivePage() {
  return (
    <div className="mx-auto min-h-screen max-w-measure">
      <header className="sticky top-0 z-10 border-b border-border bg-background/95 px-4 py-3 md:px-6">
        <p className="font-sans text-[12px] uppercase tracking-[0.16em] text-muted">Ahora</p>
        <h1 className="font-heading text-2xl font-semibold text-primary">En vivo</h1>
      </header>
      <LiveTimeline />
    </div>
  );
}
