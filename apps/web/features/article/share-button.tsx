"use client";

import { Check, Share2 } from "lucide-react";
import { useState } from "react";
import { buildSharePayload } from "@/lib/seo/share";

export function ShareButton({
  href,
  title,
  text,
  label = "Compartir",
}: {
  href: string;
  title?: string;
  text?: string;
  label?: string;
}) {
  const [copied, setCopied] = useState(false);

  async function share() {
    const payload = buildSharePayload({ title, text, path: href });
    const url = new URL(payload.path, window.location.origin).toString();
    try {
      if (navigator.share) {
        await navigator.share({
          url,
          ...(payload.title ? { title: payload.title } : {}),
          ...(payload.text ? { text: payload.text } : {}),
        });
        return;
      }
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") return;
    }
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  }

  return (
    <button
      type="button"
      onClick={() => void share()}
      aria-label={copied ? "Enlace copiado" : label}
      className="inline-flex items-center gap-1.5 font-sans text-sm text-secondary transition-colors hover:text-primary"
    >
      {copied ? <Check className="h-3.5 w-3.5" aria-hidden /> : <Share2 className="h-3.5 w-3.5" aria-hidden />}
      {copied ? "Enlace copiado" : label}
    </button>
  );
}
