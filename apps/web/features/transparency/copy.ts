export const REJECTED_DRAFT_WARNING =
  "Borrador no aprobado. Esta versión no superó los controles editoriales y puede contener errores. No forma parte de las noticias publicadas de Sin Línea.";

export const REJECTED_DRAFT_MARK = "Borrador no aprobado";

export const REJECTED_DRAFT_DESCRIPTION = "Sección disponible con una cuenta de Sin Línea.";

export const REASON_CATEGORY_LABEL: Record<string, string> = {
  incomplete_verification: "Verificación incompleta",
  missing_support: "Falta de respaldo",
  attribution: "Problema de atribución",
  overcertainty: "Exceso de certeza",
  technical: "Fallo técnico",
  general: "Control editorial",
};

export function publishedArticlePath(path: string | null | undefined): string | null {
  if (!path || !path.startsWith("/noticias/") || path.includes("://") || path.includes("\\")) return null;
  return path;
}
