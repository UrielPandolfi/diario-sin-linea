import { LocalView } from "@/features/feed/local-view";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Local",
  description: "Sucesos de tu localidad.",
  alternates: { canonical: "/local" },
};

export default function LocalPage() {
  return <LocalView />;
}
