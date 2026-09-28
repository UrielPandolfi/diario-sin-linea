"use client";

import { isPrivateAppPath } from "@/lib/auth/paths";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";

export function SignOutButton({ className = "" }: { className?: string }) {
  const pathname = usePathname();
  const router = useRouter();
  const [pending, setPending] = useState(false);

  async function signOut() {
    setPending(true);
    try {
      const response = await fetch("/api/v1/auth/logout", { method: "POST", credentials: "include" });
      if (!response.ok) return;
      if (isPrivateAppPath(pathname || "")) {
        router.push("/entrar");
      }
      router.refresh();
    } catch {
      return;
    } finally {
      setPending(false);
    }
  }

  return (
    <button
      type="button"
      onClick={() => void signOut()}
      disabled={pending}
      className={`rounded-lg px-2.5 py-2 text-left font-sans text-sm text-secondary hover:bg-hover hover:text-primary disabled:opacity-60 ${className}`}
    >
      {pending ? "Saliendo…" : "Salir"}
    </button>
  );
}
