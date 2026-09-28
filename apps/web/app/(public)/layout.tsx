import { AppShell } from "@/features/shell/app-shell";
import { readerFromCookie } from "@/lib/auth/session";
import type { ReactNode } from "react";

export default async function PublicLayout({ children }: { children: ReactNode }) {
  const reader = await readerFromCookie();
  return <AppShell authenticated={reader !== null}>{children}</AppShell>;
}
