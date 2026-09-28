import { LocalityStep } from "@/features/locality/locality-step";
import { safeReturnTo } from "@/lib/auth/return-to";

type Search = { next?: string | string[] };

export default async function OnboardingPage({ searchParams }: { searchParams: Promise<Search> }) {
  const params = await searchParams;
  const raw = typeof params.next === "string" ? params.next : null;
  return <LocalityStep next={raw ? safeReturnTo(raw, "/") : null} />;
}
