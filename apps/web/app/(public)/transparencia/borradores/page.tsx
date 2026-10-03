import { RejectedDraftsList } from "@/features/transparency/rejected-drafts-list";
import { REJECTED_DRAFT_DESCRIPTION } from "@/features/transparency/copy";
import { readerFromCookie } from "@/lib/auth/session";
import { loginPath } from "@/lib/auth/return-to";
import type { Metadata } from "next";
import { redirect } from "next/navigation";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Borradores no aprobados",
  description: REJECTED_DRAFT_DESCRIPTION,
  robots: { index: false, follow: false },
  openGraph: {
    title: "Borradores no aprobados",
    description: REJECTED_DRAFT_DESCRIPTION,
    type: "website",
  },
};

export default async function RejectedDraftsPage() {
  const reader = await readerFromCookie();
  if (!reader) redirect(loginPath("/transparencia/borradores"));
  return <RejectedDraftsList />;
}
