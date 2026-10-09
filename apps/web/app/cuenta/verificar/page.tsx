import { AuthStage } from "@/features/auth/auth-stage";
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
    <AuthStage>
      <p className="font-heading text-xs uppercase tracking-[0.16em] text-accent">Cuenta</p>
      <h2 className="mt-3 font-heading text-2xl font-medium text-primary">Confirmar email</h2>
      {token.length < 20 ? (
        <p className="mt-4 max-w-sm font-sans text-sm text-secondary">
          Falta un enlace válido. Si ya tenés sesión, pedí otro desde{" "}
          <Link href="/perfil" className="underline">
            Perfil
          </Link>
          .
        </p>
      ) : (
        <EmailVerificationConfirm token={token} />
      )}
    </AuthStage>
  );
}
