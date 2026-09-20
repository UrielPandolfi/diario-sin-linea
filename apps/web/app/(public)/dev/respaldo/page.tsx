import { ArticleBody } from "@/features/article/article-body";
import { ARTICLE_FIXTURE_BLOCKS, FIXTURE_CLAIMS } from "@/features/article/claim-evidence-fixtures";
import { notFound } from "next/navigation";

export default function RespaldoQaPage() {
  if (process.env.NODE_ENV === "production") notFound();

  return (
    <div className="mx-auto max-w-[42rem] px-4 py-8 md:px-6">
      <p className="font-sans text-[11px] uppercase tracking-[0.14em] text-muted">QA interno · C10</p>
      <h1 className="mt-3 font-heading text-3xl font-medium leading-tight text-primary">Respaldo de afirmaciones</h1>
      <p className="mt-4 font-sans text-base leading-relaxed text-secondary">
        Datos de prueba. No consulta Verification ni fuentes externas.
      </p>
      <ArticleBody
        body=""
        bodyBlocks={ARTICLE_FIXTURE_BLOCKS}
        claims={Object.values(FIXTURE_CLAIMS)}
        sourceKey="qa-respaldo:1"
      />
    </div>
  );
}
