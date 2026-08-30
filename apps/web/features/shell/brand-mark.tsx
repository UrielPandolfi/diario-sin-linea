export function BrandMark({ className = "h-8 w-8" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 32 32" fill="none" aria-hidden="true">
      <path
        d="M4 10h8M16 10h12"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeDasharray="0.1 5"
      />
      <path d="M4 16h24" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      <path
        d="M4 22h12M20 22h8"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeDasharray="0.1 5"
      />
    </svg>
  );
}
