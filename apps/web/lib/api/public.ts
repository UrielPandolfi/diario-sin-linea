import type {
  Article,
  CaseCreateResponse,
  CaseFollowUp,
  CursorPage,
  FeedScope,
  LocalitiesResponse,
  NearbyResponse,
  NowResponse,
  SearchResponse,
} from "./types";

export class PublicApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "PublicApiError";
  }
}

function apiOrigin(): string {
  if (typeof window === "undefined") {
    return process.env.API_URL ?? "http://localhost:8000";
  }
  return "";
}

function buildUrl(path: string, params?: Record<string, string | number | undefined>): string {
  const origin = apiOrigin();
  const url = new URL(`${origin}${path}`, origin || "http://localhost");
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value === undefined || value === "") continue;
      url.searchParams.set(key, String(value));
    }
  }
  if (!origin) {
    return `${url.pathname}${url.search}`;
  }
  return url.toString();
}

export async function publicGet<T>(path: string, params?: Record<string, string | number | undefined>): Promise<T> {
  const response = await fetch(buildUrl(path, params), { cache: "no-store" });
  if (!response.ok) {
    throw new PublicApiError("request_failed", response.status);
  }
  return (await response.json()) as T;
}

export function fetchFeed(options: {
  scope: FeedScope;
  locality?: string;
  cursor?: string | null;
  limit?: number;
}): Promise<CursorPage> {
  return publicGet<CursorPage>("/api/v1/feed", {
    scope: options.scope,
    locality: options.locality,
    cursor: options.cursor ?? undefined,
    limit: options.limit,
  });
}

export function fetchLocal(options: {
  locality: string;
  cursor?: string | null;
  limit?: number;
}): Promise<CursorPage> {
  return publicGet<CursorPage>("/api/v1/local", {
    locality: options.locality,
    cursor: options.cursor ?? undefined,
    limit: options.limit,
  });
}

export function fetchLive(options: { cursor?: string | null; limit?: number } = {}): Promise<CursorPage> {
  return publicGet<CursorPage>("/api/v1/live", {
    cursor: options.cursor ?? undefined,
    limit: options.limit,
  });
}

export function fetchNow(limit?: number): Promise<NowResponse> {
  return publicGet<NowResponse>("/api/v1/now", { limit });
}

export function fetchNearby(locality: string, limit?: number): Promise<NearbyResponse> {
  return publicGet<NearbyResponse>("/api/v1/nearby", { locality, limit });
}

export function fetchSearch(query: string, locality?: string, limit?: number): Promise<SearchResponse> {
  return publicGet<SearchResponse>("/api/v1/search", { q: query, locality, limit });
}

export function fetchLocalities(): Promise<LocalitiesResponse> {
  return publicGet<LocalitiesResponse>("/api/v1/localities");
}

export function fetchArticle(key: string): Promise<Article> {
  return publicGet<Article>(`/api/v1/articles/${encodeURIComponent(key)}`);
}

export async function createCase(
  body: {
    article_id?: string;
    article_slug?: string;
    reported_version_number?: number;
    reason: string;
    message: string;
    link_url?: string;
    email?: string;
    website?: string;
  },
  idempotencyKey: string,
): Promise<CaseCreateResponse> {
  const origin = apiOrigin();
  const url = origin ? `${origin}/api/v1/cases` : "/api/v1/cases";
  const response = await fetch(url, {
    method: "POST",
    cache: "no-store",
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": idempotencyKey,
    },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new PublicApiError("request_failed", response.status);
  }
  return (await response.json()) as CaseCreateResponse;
}

export async function fetchFollowUp(token: string): Promise<CaseFollowUp> {
  const origin = apiOrigin();
  const url = origin
    ? `${origin}/api/v1/cases/follow-up/${encodeURIComponent(token)}`
    : `/api/v1/cases/follow-up/${encodeURIComponent(token)}`;
  const response = await fetch(url, {
    cache: "no-store",
    headers: { "Cache-Control": "no-store" },
  });
  if (!response.ok) {
    throw new PublicApiError("request_failed", response.status);
  }
  return (await response.json()) as CaseFollowUp;
}
