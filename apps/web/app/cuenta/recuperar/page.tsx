import { AuthStage } from "@/features/auth/auth-stage";
import { PasswordResetRequestForm } from "@/features/auth/password-reset-request";
import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Recuperar contraseña",
  robots: { index: false, follow: false },
};

export default function RecoverPage() {
  return (
    <AuthStage>
      <p className="font-heading text-xs uppercase tracking-[0.16em] text-accent">Cuenta</p>
      <h2 className="mt-3 font-heading text-2xl font-medium text-primary">Olvidé mi contraseña</h2>
      <p className="mt-2 max-w-sm font-sans text-sm text-secondary">
        Si el correo está configurado y hay una cuenta con ese email, llega un enlace para elegir otra
        contraseña. La respuesta es la misma cuando el email no está registrado.
      </p>
      <PasswordResetRequestForm />
      <p className="mt-6 font-sans text-sm text-secondary">
        <Link href="/entrar">Volver a ingresar</Link>
      </p>
    </AuthStage>
  );
}
