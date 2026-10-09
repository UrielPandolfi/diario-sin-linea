import { EmailVerificationConfirm } from "@/features/auth/email-verification-confirm";
import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Confirmar email",
  robots: { index: false, follow: false },
};

type Search = { token?: string | string[] };

export default async function VerifyEmailPage({ searchParams }: { searchParams: Promise<Search> }) {
  const params = await searchParams;
  const token = typeof params.token === "string" ? params.token : "";
  return (
    <div className="mx-auto min-h-screen max-w-measure px-4 py-8 md:px-6">
      <p className="font-sans text-[12px] uppercase tracking-[0.16em] text-accent">Cuenta</p>
      <h1 className="mt-2 font-heading text-3xl font-semibold text-primary">Confirmar email</h1>
      {token.length < 20 ? (
        <p className="mt-4 font-sans text-sm text-secondary">
          Falta un enlace válido. Si ya tenés sesión, pedí otro desde{" "}
          <Link href="/perfil" className="underline">
            Perfil
          </Link>
          .
        </p>
      ) : (
        <EmailVerificationConfirm token={token} />
      )}
    </div>
  );
}
