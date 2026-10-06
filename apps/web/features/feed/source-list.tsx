"use client";

import type { ArticleSource } from "@/lib/api/types";
import { Newspaper } from "lucide-react";
import type { ReactNode } from "react";

export function SourceList({ sources }: { sources: ArticleSource[] }) {
  const named = sources.filter((source) => source.name || source.domain);
  if (named.length === 0) return null;

  const visible = named.slice(0, 2);
  const extra = named.length - visible.length;
  const compact = visible.map((source) => source.name || source.domain).join(" · ");

  return (
    <details className="group">
      <summary className="flex cursor-pointer list-none items-center gap-1.5 font-sans text-xs text-secondary marker:content-none hover:text-primary">
        <Newspaper className="h-4 w-4 shrink-0 text-[#7fb5a8]" strokeWidth={2.25} aria-hidden />
        <span>{compact}</span>
        {extra > 0 ? <span>{` +${extra}`}</span> : null}
        <span className="ml-2 hidden text-muted group-open:inline">Fuentes</span>
      </summary>
      <ul className="mt-2 space-y-1 font-sans text-xs text-secondary">
        {named.map((source, index) => {
          const label = source.name || source.domain || "Fuente";
          const href = source.url;
          return (
            <li key={`${href ?? label}-${index}`}>
              {href ? (
                <a href={href} target="_blank" rel="noreferrer" className="text-secondary hover:text-accent-blue">
                  {label}
                  {source.title ? <span className="text-muted"> — {source.title}</span> : null}
                </a>
              ) : (
                <span>
                  {label}
                  {source.title ? <span className="text-muted"> — {source.title}</span> : null}
                </span>
              )}
            </li>
          );
        })}
      </ul>
    </details>
  );
}

export function CardActions({ save, share }: { save?: ReactNode; share: ReactNode }) {
  return (
    <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1">
      {save}
      {share}
    </div>
  );
}
