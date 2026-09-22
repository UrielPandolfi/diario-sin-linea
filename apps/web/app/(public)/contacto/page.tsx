import { CaseForm } from "@/features/cases/case-form";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Contacto",
  description: "Consultas generales a Sin Línea, sin crear una cuenta.",
  alternates: { canonical: "/contacto" },
};

export default function ContactoPage() {
  return (
    <div className="mx-auto min-h-screen max-w-measure px-4 py-8 md:px-6">
      <p className="font-sans text-[12px] uppercase tracking-[0.16em] text-muted">Contacto</p>
      <h1 className="mt-2 font-heading text-3xl font-semibold text-primary">Escribinos</h1>
      <p className="mt-3 font-sans text-sm text-secondary">
        Para consultas generales. Si se trata de una noticia concreta, reportala al final de esa
        página. El seguimiento es por un enlace privado; no enviamos correos automáticos.
      </p>
      <CaseForm storageKey="case-idempotency:contacto" />
    </div>
  );
}