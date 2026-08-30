export function FeedSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div aria-busy="true" aria-live="polite">
      <span className="sr-only">Cargando suceso…</span>
      {Array.from({ length: rows }, (_, index) => (
        <div key={index} className="animate-pulse border-b border-border px-4 py-4 md:px-5">
          <div className="h-2 w-28 bg-surface-secondary" />
          <div className="mt-3 h-5 w-11/12 bg-surface-secondary" />
          <div className="mt-2 h-4 w-full bg-surface-secondary" />
          <div className="mt-2 h-4 w-2/3 bg-surface-secondary" />
        </div>
      ))}
    </div>
  );
}

export function FeedEmpty({ title, description }: { title: string; description: string }) {
  return (
    <div className="px-5 py-16 text-center">
      <p className="font-heading text-lg text-primary">{title}</p>
      <p className="mt-2 font-sans text-sm text-secondary">{description}</p>
    </div>
  );
}

export function FeedError({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="px-5 py-12 text-center">
      <p className="font-heading text-base text-primary">No pudimos actualizar el feed.</p>
      <button
        type="button"
        onClick={onRetry}
        className="mt-4 border border-border bg-hover px-3 py-1.5 font-sans text-sm text-primary hover:bg-surface-secondary"
      >
        Reintentar
      </button>
    </div>
  );
}
