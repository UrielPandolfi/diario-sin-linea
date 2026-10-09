import { AuthStage } from "@/features/auth/auth-stage";
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
    <AuthStage>
      <p className="font-heading text-xs uppercase tracking-[0.16em] text-accent">Cuenta</p>
      <h2 className="mt-3 font-heading text-2xl font-medium text-primary">Elegí una contraseña nueva</h2>
      {token.length < 20 ? (
        <p className="mt-4 max-w-sm font-sans text-sm text-secondary">
          Falta un enlace válido.{" "}
          <Link href="/cuenta/recuperar" className="underline">
            Pedí uno nuevo
          </Link>
          .
        </p>
      ) : (
        <PasswordResetConfirmForm token={token} />
      )}
      <p className="mt-6 font-sans text-sm text-secondary">
        <Link href="/entrar">Volver a ingresar</Link>
      </p>
    </AuthStage>
  );
}
