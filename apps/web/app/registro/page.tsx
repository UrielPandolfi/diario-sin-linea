import { AuthFrame } from "@/features/auth/auth-frame";
import { readerFromCookie } from "@/lib/auth/session";
import { safeReturnTo } from "@/lib/auth/return-to";
import type { Metadata } from "next";
import { redirect } from "next/navigation";

export const metadata: Metadata = {
  title: "Crear cuenta",
  robots: { index: false, follow: false },
};

type Search = { next?: string | string[] };

export default async function RegistroPage({ searchParams }: { searchParams: Promise<Search> }) {
  const params = await searchParams;
  const raw = typeof params.next === "string" ? params.next : null;
  const next = raw ? safeReturnTo(raw, "/") : null;
  if (raw && raw !== next) {
    redirect(`/registro?next=${encodeURIComponent(next ?? "/")}`);
  }
  if (await readerFromCookie()) {
    redirect(next ?? "/");
  }
  return <AuthFrame mode="register" next={next} />;
}
