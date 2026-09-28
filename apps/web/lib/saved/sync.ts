"use client";

type Listener = (slug: string, saved: boolean) => void;

const listeners = new Set<Listener>();

export function publishSaved(slug: string, saved: boolean): void {
  for (const listener of listeners) listener(slug, saved);
}

export function subscribeSaved(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
