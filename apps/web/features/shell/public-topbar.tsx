"use client";

import { SignOutButton } from "@/features/auth/sign-out-button";
import { ThemeToggle } from "@/components/theme-toggle";
import Link from "next/link";

export function PublicTopBar({ desktop = true, authenticated = false }: { desktop?: boolean; authenticated?: boolean }) {
  return (
    <div
      className={`flex items-center gap-3 border-b border-border bg-background/80 px-4 py-1.5 backdrop-blur-md md:px-6 ${
        desktop ? "justify-between" : "justify-between md:hidden"
      }`}
    >
      <Link href="/" className="flex items-center lg:hidden" aria-label="Sin Línea">
        <span className="sl-logo h-8 w-[11.375rem]" />
      </Link>
      <div className="ml-auto flex items-center gap-1">
        {authenticated ? <SignOutButton className="md:hidden" /> : null}
        <ThemeToggle />
      </div>
    </div>
  );
}
