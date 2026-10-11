"use client";

import { LocalitySearch } from "@/features/locality/locality-search";
import { safeReturnTo } from "@/lib/auth/return-to";
import Link from "next/link";
import { useRouter } from "next/navigation";

export function LocalityStep({ next }: { next: string | null }) {
  const router = useRouter();
  const destination = safeReturnTo(next, "/");

  function finish() {
    router.push(destination);
    router.refresh();
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center bg-background px-6 py-12">
      <Link href="/" className="inline-flex items-center" aria-label="Sin Línea">
        <span className="sl-logo h-8 w-[11.375rem]" />
      </Link>
      <h1 className="mt-10 font-heading text-3xl font-semibold text-primary">
        ¿De qué localidad querés estar al tanto?
      </h1>
      <p className="mt-3 font-sans text-sm leading-relaxed text-secondary">
        La usamos para mostrarte noticias cercanas. Podés cambiarla cuando quieras.
      </p>
      <div className="mt-8">
        <LocalitySearch mode="prompt" onFinished={finish} />
      </div>
    </main>
  );
}
