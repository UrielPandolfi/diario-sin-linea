"use client";

import { SectionContextBar, SectionRail } from "@/features/shell/home-rail";
import { fetchReaderAccount, placeLabel } from "@/lib/auth/account";
import { useEffect, useState, type ReactNode } from "react";

export function SectionFrame({
  now = false,
  nearby = false,
  label,
  children,
}: {
  now?: boolean;
  nearby?: boolean;
  label?: string | null;
  children: ReactNode;
}) {
  const provided = label !== undefined;
  const [resolved, setResolved] = useState<string | null>(label ?? null);
  const [pending, setPending] = useState(!provided && nearby);

  useEffect(() => {
    if (provided) {
      setResolved(label ?? null);
      setPending(false);
      return;
    }
    if (!nearby) {
      setPending(false);
      return;
    }
    let cancelled = false;
    setPending(true);
    void fetchReaderAccount()
      .then((account) => {
        if (cancelled) return;
        setResolved(account.locality ? placeLabel(account.locality) : null);
      })
      .catch(() => {
        if (!cancelled) setResolved(null);
      })
      .finally(() => {
        if (!cancelled) setPending(false);
      });
    return () => {
      cancelled = true;
    };
  }, [label, nearby, provided]);

  return (
    <div className="flex min-h-screen">
      <div className="min-w-0 flex-1 border-r border-border">
        <SectionContextBar label={resolved} now={now} nearby={nearby} pending={pending} />
        {children}
      </div>
      <SectionRail label={resolved} now={now} nearby={nearby} pending={pending} />
    </div>
  );
}
