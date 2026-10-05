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
      <LiveTimeline />
    </div>
  );
}
