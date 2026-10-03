import { RejectedDraftView } from "@/features/transparency/rejected-draft-view";
import { REJECTED_DRAFT_DESCRIPTION } from "@/features/transparency/copy";
import { readerFromCookie } from "@/lib/auth/session";
import { loginPath } from "@/lib/auth/return-to";
import type { Metadata } from "next";
import { redirect } from "next/navigation";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Borrador no aprobado",
  description: REJECTED_DRAFT_DESCRIPTION,
  robots: { index: false, follow: false },
  openGraph: {
    title: "Borrador no aprobado",
    description: REJECTED_DRAFT_DESCRIPTION,
    type: "website",
  },
};

type Params = { id: string };

export default async function RejectedDraftPage({ params }: { params: Promise<Params> }) {
  const { id } = await params;
  const reader = await readerFromCookie();
  if (!reader) redirect(loginPath(`/transparencia/borradores/${id}`));
  return <RejectedDraftView articleId={id} />;
}
