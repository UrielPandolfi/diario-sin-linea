"use client";

import { BrandMark } from "@/features/shell/brand-mark";
import { ThemeToggle } from "@/components/theme-toggle";
import Link from "next/link";

export function PublicTopBar({ desktop = true }: { desktop?: boolean }) {
  return (
    <div
      className={`flex items-center gap-3 border-b border-border bg-background px-4 py-1.5 md:px-6 ${
        desktop ? "justify-between" : "justify-between md:hidden"
      }`}
    >
      <Link href="/" className="flex items-center gap-2 text-primary lg:hidden">
        <BrandMark className="h-7 w-7" />
        <span className="font-heading text-[13px] font-medium tracking-[0.14em]">Sin Línea</span>
      </Link>
      <div className="ml-auto flex items-center">
        <ThemeToggle />
      </div>
    </div>
  );
}
