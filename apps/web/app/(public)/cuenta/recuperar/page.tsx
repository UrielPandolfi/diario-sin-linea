import { PasswordResetRequestForm } from "@/features/auth/password-reset-request";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Recuperar contraseña",
  robots: { index: false, follow: false },
};

export default function RecoverPage() {
  return (
    <div className="mx-auto min-h-screen max-w-measure px-4 py-8 md:px-6">
      <p className="font-sans text-[12px] uppercase tracking-[0.16em] text-muted">Cuenta</p>
      <h1 className="mt-2 font-heading text-3xl font-semibold text-primary">Olvidé mi contraseña</h1>
      <p className="mt-3 max-w-md font-sans text-sm text-secondary">
        Si el correo está configurado y hay una cuenta con ese email, llega un enlace para elegir otra
        contraseña. La respuesta es la misma cuando el email no está registrado.
      </p>
      <PasswordResetRequestForm />
    </div>
  );
}
