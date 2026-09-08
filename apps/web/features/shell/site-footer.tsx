import Link from "next/link";

export function SiteFooter() {
  return (
    <footer className="border-t border-border px-4 py-6 md:px-6">
      <nav aria-label="Sitio" className="flex flex-wrap gap-4 font-sans text-sm text-secondary">
        <Link href="/contacto" className="hover:text-primary">
          Contacto
        </Link>
        <Link href="/como-funciona" className="hover:text-primary">
          Cómo funciona
        </Link>
      </nav>
    </footer>
  );
}