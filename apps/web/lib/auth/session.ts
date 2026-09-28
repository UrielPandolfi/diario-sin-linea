import { cookies } from "next/headers";

import { readerSessionSecret } from "@/lib/auth/secret";
import { READER_COOKIE, verifyReaderToken } from "@/lib/auth/session-token";

export async function readerFromCookie(): Promise<{ sub: string } | null> {
  const jar = await cookies();
  const sub = await verifyReaderToken(jar.get(READER_COOKIE)?.value, readerSessionSecret());
  return sub ? { sub } : null;
}
