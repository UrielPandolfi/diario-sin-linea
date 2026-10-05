import { LiveTimeline } from "@/features/live/live-timeline";
import { SectionFrame } from "@/features/shell/section-frame";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "En vivo",
  description: "Sucesos publicados, ordenados por la última actualización.",
  alternates: { canonical: "/en-vivo" },
};

export default function LivePage() {
  return (
    <SectionFrame nearby>
      <LiveTimeline />
    </SectionFrame>
  );
}
