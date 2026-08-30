"use client";

import { UpcomingAction } from "@/features/upcoming/upcoming-feature";
import type { ArticleSource } from "@/lib/api/types";
import { MessageCircle, UserPlus } from "lucide-react";
import type { ReactNode } from "react";

export function SourceList({ sources }: { sources: ArticleSource[] }) {
  const named = sources.filter((source) => source.name || source.domain);
  if (named.length === 0) return null;

  const visible = named.slice(0, 2);
  const extra = named.length - visible.length;
  const compact = visible.map((source) => source.name || source.domain).join(" · ");

  return (
    <details className="group">
      <summary className="cursor-pointer list-none font-sans text-xs text-secondary marker:content-none hover:text-primary">
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

export function CardActions({ share }: { share: ReactNode }) {
  return (
    <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1">
      <UpcomingAction>
        <UserPlus className="h-3.5 w-3.5" aria-hidden />
        Seguir
      </UpcomingAction>
      <UpcomingAction>
        <MessageCircle className="h-3.5 w-3.5" aria-hidden />
        Comentar
      </UpcomingAction>
      {share}
    </div>
  );
}
