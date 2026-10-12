import Script from "next/script";

import { PLAUSIBLE_SCRIPT_SRC, plausibleInitSnippet } from "@/lib/analytics/plausible";

export function PlausibleAnalytics({ enabled }: { enabled: boolean }) {
  if (!enabled) return null;
  return (
    <>
      <Script id="sin-linea-plausible" src={PLAUSIBLE_SCRIPT_SRC} strategy="afterInteractive" />
      <Script id="sin-linea-plausible-init" strategy="afterInteractive">
        {plausibleInitSnippet()}
      </Script>
    </>
  );
}
