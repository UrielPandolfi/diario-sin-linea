"use client";

import { PublicTopBar } from "@/features/shell/public-topbar";
import { MobileNav } from "@/features/shell/mobile-nav";
import { Sidebar } from "@/features/shell/sidebar";
import { SiteFooter } from "@/features/shell/site-footer";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const articlePage = pathname?.startsWith("/noticias/") ?? false;

  return (
    <div className="min-h-screen bg-background">
      <div className="mx-auto flex min-h-screen max-w-[92rem]">
        <Sidebar />
        <div className="flex min-w-0 flex-1 flex-col pb-16 md:pb-0">
          <PublicTopBar desktop={!articlePage} />
          <div className="min-w-0 flex-1">{children}</div>
          <SiteFooter />
        </div>
      </div>
      <MobileNav />
    </div>
  );
}
