import { MobileNav } from "@/features/shell/mobile-nav";
import { Sidebar } from "@/features/shell/sidebar";
import type { ReactNode } from "react";

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen bg-background">
      <div className="mx-auto flex min-h-screen max-w-[1440px]">
        <Sidebar />
        <div className="min-w-0 flex-1 pb-16 md:pb-0">{children}</div>
      </div>
      <MobileNav />
    </div>
  );
}
