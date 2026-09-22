import { ArticleBody } from "@/features/article/article-body";
import { ARTICLE_FIXTURE_BLOCKS, FIXTURE_CLAIMS } from "@/features/article/claim-evidence-fixtures";
import { notFound } from "next/navigation";

export default function RespaldoQaPage() {
  if (process.env.NODE_ENV === "production") notFound();

  return (
    <div className="article-root mx-auto w-full max-w-article px-4 py-8 md:px-8">
      <div className="grid grid-cols-1 xl:grid-cols-[var(--article-measure)_var(--article-panel)] xl:gap-x-[var(--article-gap)]">
        <div className="min-w-0 max-w-[var(--article-measure)]">
          <p className="font-sans text-[12px] uppercase tracking-[0.14em] text-muted">QA interno · C10</p>
          <h1 className="article-title mt-3">Respaldo de afirmaciones</h1>
          <p className="article-dek mt-4">Datos de prueba. No consulta Verification ni fuentes externas.</p>
          <p className="mt-6 font-sans text-[13px] text-secondary">
            Explorá las frases subrayadas para conocer su respaldo.
          </p>
          <ArticleBody
            body=""
            bodyBlocks={ARTICLE_FIXTURE_BLOCKS}
            claims={Object.values(FIXTURE_CLAIMS)}
            sourceKey="qa-respaldo:1"
          />
        </div>
        <aside data-evidence-column className="relative hidden min-h-[12rem] xl:block" aria-hidden="true" />
      </div>
    </div>
  );
}
