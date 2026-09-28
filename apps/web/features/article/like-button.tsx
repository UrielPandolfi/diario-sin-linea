"use client";

import { PublicApiError } from "@/lib/api/public";
import { loginPath } from "@/lib/auth/return-to";
import { Heart } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

export function LikeButton({
  slug,
  guest,
  returnTo,
}: {
  slug: string;
  guest: boolean;
  returnTo: string;
}) {
  const [liked, setLiked] = useState<boolean | null>(null);
  const [pending, setPending] = useState(false);

  useEffect(() => {
    if (guest) return;
    let cancelled = false;
    void fetch(`/api/v1/articles/${encodeURIComponent(slug)}/like`, { cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) throw new PublicApiError("request_failed", response.status);
        return (await response.json()) as { liked: boolean };
      })
      .then((payload) => {
        if (!cancelled) setLiked(payload.liked);
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        if (error instanceof PublicApiError && error.status === 401) {
          window.location.assign(loginPath(returnTo));
          return;
        }
        setLiked(false);
      });
    return () => {
      cancelled = true;
    };
  }, [guest, returnTo, slug]);

  if (guest) {
    return (
      <Link
        href={loginPath(returnTo)}
        className="inline-flex items-center gap-1.5 font-sans text-sm text-secondary hover:text-primary"
      >
        <Heart className="h-3.5 w-3.5" aria-hidden />
        Me gusta
      </Link>
    );
  }

  async function toggle() {
    if (liked === null || pending) return;
    setPending(true);
    try {
      const response = await fetch(`/api/v1/articles/${encodeURIComponent(slug)}/like`, {
        method: liked ? "DELETE" : "PUT",
        cache: "no-store",
      });
      if (response.status === 401) {
        window.location.assign(loginPath(returnTo));
        return;
      }
      if (!response.ok) return;
      const payload = (await response.json()) as { liked: boolean };
      setLiked(payload.liked);
    } finally {
      setPending(false);
    }
  }

  return (
    <button
      type="button"
      onClick={() => void toggle()}
      aria-pressed={liked === true}
      disabled={liked === null || pending}
      className="inline-flex items-center gap-1.5 font-sans text-sm text-secondary transition-colors hover:text-primary disabled:opacity-60"
    >
      <Heart className="h-3.5 w-3.5" aria-hidden fill={liked ? "currentColor" : "none"} />
      Me gusta
    </button>
  );
}
