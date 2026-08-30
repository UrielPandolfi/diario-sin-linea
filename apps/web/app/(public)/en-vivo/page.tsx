import { LiveTimeline } from "@/features/live/live-timeline";

export const metadata = {
  title: "En vivo",
};

export default function LivePage() {
  return (
    <div className="mx-auto min-h-screen max-w-2xl border-x border-border">
      <header className="sticky top-0 z-10 border-b border-border bg-background px-4 py-3 md:px-5">
        <p className="font-heading text-xs uppercase tracking-[0.16em] text-accent-ochre">Ahora</p>
        <h1 className="font-heading text-lg text-primary">En vivo</h1>
      </header>
      <LiveTimeline />
    </div>
  );
}
