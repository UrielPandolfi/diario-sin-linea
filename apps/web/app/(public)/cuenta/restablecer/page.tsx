import { PasswordResetConfirmForm } from "@/features/auth/password-reset-confirm";
import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Nueva contraseña",
  robots: { index: false, follow: false },
};

type Search = { token?: string | string[] };

export default async function ResetPage({ searchParams }: { searchParams: Promise<Search> }) {
  const params = await searchParams;
  const token = typeof params.token === "string" ? params.token : "";
  return (
    <div className="mx-auto min-h-screen max-w-measure px-4 py-8 md:px-6">
      <p className="font-sans text-[12px] uppercase tracking-[0.16em] text-muted">Cuenta</p>
      <h1 className="mt-2 font-heading text-3xl font-semibold text-primary">Elegí una contraseña nueva</h1>
      {token.length < 20 ? (
        <p className="mt-4 font-sans text-sm text-secondary">
          Falta un enlace válido.{" "}
          <Link href="/cuenta/recuperar" className="underline">
            Pedí uno nuevo
          </Link>
          .
        </p>
      ) : (
        <PasswordResetConfirmForm token={token} />
      )}
    </div>
  );
}
