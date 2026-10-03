import { REJECTED_DRAFT_DESCRIPTION } from "@/features/transparency/copy";
import type { Metadata } from "next";
import type { ReactNode } from "react";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Transparencia",
  description: REJECTED_DRAFT_DESCRIPTION,
  robots: { index: false, follow: false },
  openGraph: {
    title: "Transparencia",
    description: REJECTED_DRAFT_DESCRIPTION,
    type: "website",
  },
};

export default function TransparencyLayout({ children }: { children: ReactNode }) {
  return children;
}
