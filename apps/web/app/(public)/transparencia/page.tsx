import { REJECTED_DRAFT_DESCRIPTION } from "@/features/transparency/copy";
import { readerFromCookie } from "@/lib/auth/session";
import { loginPath } from "@/lib/auth/return-to";
import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Transparencia",
  description: REJECTED_DRAFT_DESCRIPTION,
  robots: { index: false, follow: false },
};

export default async function TransparencyPage() {
  const reader = await readerFromCookie();
  if (!reader) redirect(loginPath("/transparencia"));

  return (
    <div className="mx-auto min-h-screen max-w-measure px-4 py-8 md:px-6">
      <p className="font-sans text-[12px] uppercase tracking-[0.16em] text-accent">Perfil</p>
      <h1 className="mt-2 font-heading text-3xl font-semibold text-primary">Transparencia</h1>
      <p className="mt-3 max-w-xl font-sans text-sm leading-relaxed text-secondary">
        Material que no forma parte de las noticias publicadas.
      </p>
      <section className="sl-block sl-enter mt-8 p-5">
        <h2 className="font-heading text-xl text-primary">
          <Link href="/transparencia/borradores" className="text-primary hover:text-accent">
            Borradores no aprobados
          </Link>
        </h2>
        <p className="mt-2 font-sans text-sm leading-relaxed text-secondary">
          Versiones con texto guardado cuya evaluación impidió publicarlas.
        </p>
      </section>
    </div>
  );
}
