"use client";

import { ShareButton } from "@/features/article/share-button";
import { CardActions, SourceList } from "@/features/feed/source-list";
import { RelativeTime } from "@/components/relative-time";
import type { EventCard as EventCardType } from "@/lib/api/types";
import { isMateriallyUpdated } from "@/lib/relative-time";
import Link from "next/link";

export function EventCard({ item }: { item: EventCardType }) {
  const href = `/noticias/${item.slug}`;
  const updated = isMateriallyUpdated(item.published_at, item.updated_at);

  return (
    <article className="border-b border-border px-4 py-4 md:px-5">
      <p className="font-sans text-[11px] uppercase tracking-[0.14em] text-muted">
        {item.locality ? <span>{item.locality}</span> : null}
        {item.locality && item.published_at ? <span> · </span> : null}
        <RelativeTime iso={item.published_at} />
      </p>
      <h2 className="mt-1.5 font-heading text-lg font-medium leading-snug text-primary">
        <Link href={href} className="text-primary hover:text-accent-blue">
          {item.headline}
        </Link>
      </h2>
      {item.summary ? <p className="mt-2 font-sans text-sm leading-relaxed text-secondary">{item.summary}</p> : null}
      <div className="mt-3">
        <SourceList sources={item.sources} />
      </div>
      {updated ? (
        <p className="mt-2 font-sans text-xs text-muted">
          Actualizado <RelativeTime iso={item.updated_at} />
        </p>
      ) : null}
      <CardActions share={<ShareButton href={href} />} />
    </article>
  );
}
