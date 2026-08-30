import Link from "next/link";

export default function ArticleNotFound() {
  return (
    <div className="mx-auto max-w-md px-6 py-24 text-center">
      <h1 className="font-heading text-2xl text-primary">No encontramos esa noticia.</h1>
      <p className="mt-2 font-sans text-sm text-secondary">Puede haber sido archivada o el enlace está incompleto.</p>
      <Link href="/" className="mt-6 inline-block font-sans text-sm text-primary">
        Volver al inicio
      </Link>
    </div>
  );
}
