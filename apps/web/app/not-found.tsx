import { NO_INDEX_NO_FOLLOW } from "@/lib/seo/metadata";
import Link from "next/link";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "No encontrado",
  robots: NO_INDEX_NO_FOLLOW,
};

export default function RootNotFound() {
  return (
    <div className="mx-auto max-w-md px-6 py-24 text-center">
      <h1 className="font-heading text-2xl text-primary">No encontramos esa página.</h1>
      <p className="mt-2 font-sans text-sm text-secondary">El enlace puede estar incompleto o ya no existe.</p>
      <Link href="/" className="mt-6 inline-block font-sans text-sm text-primary">
        Volver al inicio
      </Link>
    </div>
  );
}
