import { localityLabel } from "@/lib/locality/label";

export type ReaderPlace = {
  id: string;
  name: string;
  province_id: string;
  province_name: string;
  department_id: string;
  department_name: string;
  country_code: string;
  show_department: boolean;
};

export type ReaderAccount = {
  authenticated: boolean;
  email: string | null;
  email_verified: boolean | null;
  locality_step: "pending" | "done" | "skipped" | null;
  locality: ReaderPlace | null;
};

export function placeLabel(place: ReaderPlace): string {
  return localityLabel(place);
}

async function readerFetch(path: string, init?: RequestInit): Promise<Response> {
  return fetch(path, {
    ...init,
    credentials: "include",
    cache: "no-store",
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });
}

export async function fetchReaderAccount(): Promise<ReaderAccount> {
  const response = await readerFetch("/api/v1/auth/session");
  if (!response.ok) {
    return { authenticated: false, email: null, email_verified: null, locality_step: null, locality: null };
  }
  const body = (await response.json()) as {
    authenticated?: boolean;
    email?: string;
    email_verified?: boolean;
    locality_step?: ReaderAccount["locality_step"];
    locality?: ReaderPlace | null;
  };
  if (!body.authenticated) {
    return { authenticated: false, email: null, email_verified: null, locality_step: null, locality: null };
  }
  return {
    authenticated: true,
    email: typeof body.email === "string" ? body.email : null,
    email_verified: typeof body.email_verified === "boolean" ? body.email_verified : null,
    locality_step: body.locality_step ?? null,
    locality: body.locality ?? null,
  };
}

export async function searchLocalities(query: string, signal?: AbortSignal): Promise<ReaderPlace[]> {
  const response = await readerFetch(`/api/v1/geo/localities?q=${encodeURIComponent(query)}`, { signal });
  if (!response.ok) {
    throw new Error("search_failed");
  }
  const body = (await response.json()) as { items?: ReaderPlace[] };
  return Array.isArray(body.items) ? body.items : [];
}

export async function saveReaderLocality(localityId: string): Promise<ReaderPlace> {
  const response = await readerFetch("/api/v1/auth/locality", {
    method: "PUT",
    body: JSON.stringify({ locality_id: localityId }),
  });
  if (response.status === 404) {
    throw new Error("missing");
  }
  if (!response.ok) {
    throw new Error("save_failed");
  }
  const body = (await response.json()) as { locality?: ReaderPlace | null };
  if (!body.locality) {
    throw new Error("save_failed");
  }
  return body.locality;
}

export async function skipReaderLocality(): Promise<void> {
  const response = await readerFetch("/api/v1/auth/locality/skip", { method: "POST" });
  if (!response.ok) {
    throw new Error("skip_failed");
  }
}

export async function clearReaderLocality(): Promise<void> {
  const response = await readerFetch("/api/v1/auth/locality", { method: "DELETE" });
  if (!response.ok) {
    throw new Error("clear_failed");
  }
}
