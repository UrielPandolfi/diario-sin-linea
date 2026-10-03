"use client";

import { EventCard } from "@/features/feed/event-card";
import { FeedEmpty, FeedError, FeedSkeleton } from "@/features/feed/feed-states";
import { PublicApiError, fetchSearch } from "@/lib/api/public";
import { loginPath } from "@/lib/auth/return-to";
import type { EventCard as EventCardType } from "@/lib/api/types";
import { Search } from "lucide-react";
import { FormEvent, useState } from "react";

export function SearchView() {
  const [query, setQuery] = useState("");
  const [submitted, setSubmitted] = useState("");
  const [items, setItems] = useState<EventCardType[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);

  async function run(value: string) {
    const q = value.trim();
    setSubmitted(q);
    if (!q) {
      setItems([]);
      setError(false);
      return;
    }
    setLoading(true);
    setError(false);
    try {
      const payload = await fetchSearch(q);
      setItems(payload.items);
    } catch (error) {
      if (error instanceof PublicApiError && error.status === 401) {
        window.location.assign(loginPath("/buscar"));
        return;
      }
      setError(true);
      setItems([]);
    } finally {
      setLoading(false);
    }
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    void run(query);
  }

  return (
    <div>
      <form onSubmit={onSubmit} className="border-b border-border px-4 py-4 md:px-5">
        <label className="sr-only" htmlFor="search-q">
          Buscar sucesos, lugares o personas
        </label>
        <div className="sl-block flex items-center gap-2 px-3 py-2.5">
          <Search className="h-4 w-4 shrink-0 text-muted" aria-hidden />
          <input
            id="search-q"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Buscar sucesos, lugares o personas..."
            className="w-full bg-transparent font-sans text-sm text-primary outline-none placeholder:text-muted"
            autoComplete="off"
          />
          <button
            type="submit"
            className="sl-chip shrink-0"
          >
            Buscar
          </button>
        </div>
      </form>
      {loading ? <FeedSkeleton /> : null}
      {error ? <FeedError onRetry={() => void run(submitted)} /> : null}
      {!loading && !error && submitted && items.length === 0 ? (
        <FeedEmpty
          title={`No encontramos sucesos para «${submitted}».`}
          description="Probá con otro titular, lugar o nombre."
        />
      ) : null}
      {!loading && !error
        ? items.map((item) => <EventCard key={item.public_id} item={item} />)
        : null}
    </div>
  );
}
