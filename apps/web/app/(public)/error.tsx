"use client";

export default function PublicError({
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="mx-auto max-w-md px-6 py-24 text-center">
      <p className="font-heading text-lg text-primary">No pudimos cargar esta página.</p>
      <button
        type="button"
        onClick={reset}
        className="mt-4 border border-border bg-hover px-3 py-1.5 font-sans text-sm text-primary"
      >
        Reintentar
      </button>
    </div>
  );
}
