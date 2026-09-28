import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: "Ingresar",
  robots: { index: false, follow: false },
};

export default function EntrarLayout({ children }: { children: ReactNode }) {
  return children;
}
