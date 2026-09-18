import Image from "next/image";
import Link from "next/link";

export function PublicHero({
  src,
  href,
  sizes,
  priority = false,
  className,
}: {
  src: string;
  href?: string;
  sizes: string;
  priority?: boolean;
  className?: string;
}) {
  const frame = (
    <div className={`relative aspect-[1200/630] overflow-hidden bg-surface ${className ?? ""}`.trim()}>
      <Image src={src} alt="" fill className="object-cover" sizes={sizes} priority={priority} unoptimized />
    </div>
  );
  if (!href) return frame;
  return (
    <Link href={href} className="block text-primary">
      {frame}
    </Link>
  );
}
