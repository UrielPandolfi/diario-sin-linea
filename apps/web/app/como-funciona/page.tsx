import { HowItWorksPage } from "@/features/how-it-works/how-it-works-page";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Cómo funciona",
  description:
    "Cómo Sin Línea detecta sucesos, contrasta fuentes, evalúa afirmaciones y publica información que se puede rastrear.",
  alternates: { canonical: "/como-funciona" },
};

export default function ComoFuncionaRoute() {
  return <HowItWorksPage />;
}
