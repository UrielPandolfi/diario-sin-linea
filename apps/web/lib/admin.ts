export type AdminStats = {
  monitored_sources: number;
  source_items_24h: number;
  events_24h: number;
  failed_runs_24h: number;
};

export type AdminSource = {
  id: string;
  name: string;
  domain: string | null;
  homepage_url: string | null;
  source_type: string | null;
  preferred_ingestion_method: string;
  feed_url: string | null;
  endpoint_url: string | null;
  is_monitored: boolean;
  is_enabled: boolean;
  last_success_at: string | null;
  last_failure_at: string | null;
  failure_count: number;
};

export type AdminSourceItem = {
  id: string;
  source_id: string;
  url: string;
  canonical_url: string | null;
  title: string | null;
  published_at: string | null;
  detected_at: string | null;
  processing_status: string;
};

export type AdminEvent = {
  id: string;
  title_internal: string;
  event_type: string;
  status: string;
  locality: string | null;
  province: string | null;
  short_summary: string | null;
  detected_at: string | null;
  started_at: string | null;
};

export type AdminEventDetail = AdminEvent & {
  country_code: string | null;
  neighborhood: string | null;
  address_text: string | null;
  sources: {
    relation_type: string;
    is_primary: boolean;
    source_item: AdminSourceItem | null;
  }[];
  entities: {
    id: string;
    name: string | null;
    entity_type: string | null;
    role: string;
  }[];
  pipeline_runs: {
    id: string;
    stage: string;
    status: string;
    attempt: number;
    error_message: string | null;
    started_at: string | null;
    finished_at: string | null;
  }[];
  claims: {
    id: string;
    canonical_text: string;
    status: string;
    importance: string;
    claim_type: string | null;
    evidence: {
      evidence_type: string;
      excerpt: string | null;
      source_item_id: string;
    }[];
  }[];
};

export async function adminFetch(path: string, init: RequestInit = {}) {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(path, {
    ...init,
    headers,
    credentials: "include",
  });
  if (response.status === 401) {
    window.location.href = "/admin/login";
    throw new Error("No autenticado");
  }
  return response;
}

export async function adminJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await adminFetch(path, init);
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Error ${response.status}`);
  }
  return (await response.json()) as T;
}

export function formatWhen(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("es-AR", { dateStyle: "short", timeStyle: "short" });
}
