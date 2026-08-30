export type AdminTokenTotals = {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  calls: number;
};

export type AdminTokenByRole = AdminTokenTotals & {
  model_role: string;
};

export type AdminStats = {
  monitored_sources: number;
  source_items_24h: number;
  events_24h: number;
  failed_runs_24h: number;
  running_by_stage?: Record<string, number>;
  runs_by_stage_status_24h?: { stage: string; status: string; count: number }[];
  items_by_status?: Record<string, number>;
  tokens_24h?: AdminTokenTotals;
  tokens_by_role_24h?: AdminTokenByRole[];
  last_failed_error?: string | null;
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
  pipeline_stage?: string | null;
  pipeline_run_status?: string | null;
  tokens_total?: number;
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
    metadata_json?: Record<string, unknown>;
  }[];
  token_usage?: AdminTokenTotals & {
    by_role_stage: (AdminTokenTotals & { model_role: string; stage: string })[];
  };
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
  article: {
    id: string;
    headline: string;
    summary: string;
    body: string;
    status: string;
    current_version: number;
    published_version: number | null;
    published_at: string | null;
    slug: string;
  } | null;
  audit: {
    run_id: string;
    status: string;
    passed: boolean | null;
    cap_exhausted: boolean;
    rewrite_count: number | null;
    audit_count: number | null;
    issues: {
      type: string;
      severity: string;
      text: string;
      explanation: string;
      suggested_fix: string | null;
    }[];
    reason: string | null;
    error_message: string | null;
  } | null;
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

export function formatDuration(startedAt: string | null | undefined, finishedAt: string | null | undefined): string {
  if (!startedAt || !finishedAt) return "—";
  const start = new Date(startedAt).getTime();
  const end = new Date(finishedAt).getTime();
  if (Number.isNaN(start) || Number.isNaN(end) || end < start) return "—";
  const ms = end - start;
  if (ms < 1000) return `${ms} ms`;
  const sec = ms / 1000;
  if (sec < 60) return `${sec.toFixed(1)} s`;
  return `${(sec / 60).toFixed(1)} min`;
}

export function formatTokens(value: number | null | undefined): string {
  if (value == null) return "—";
  return value.toLocaleString("es-AR");
}

export const EVENT_STATUS_LABELS: Record<string, string> = {
  DETECTED: "Detectado",
  PROCESSING: "En proceso",
  READY_FOR_REVIEW: "Listo para revisión",
  PUBLISHED: "Publicado",
  UPDATING: "Actualizando",
  CLOSED: "Cerrado",
  ARCHIVED: "Archivado",
  FAILED: "Fallido",
};

export const PIPELINE_STATUS_LABELS: Record<string, string> = {
  PENDING: "Pendiente",
  RUNNING: "En curso",
  SUCCESS: "Éxito",
  RETRY: "Reintento",
  FAILED: "Falló",
};

export const PIPELINE_STAGE_LABELS: Record<string, string> = {
  event_detection: "Detección",
  research: "Investigación",
  claim_resolution: "Claims",
  verification: "Verificación",
  writing: "Redacción",
  auditing: "Auditoría",
  publishing: "Publicación",
};

export const EVENT_STATUS_OPTIONS = Object.keys(EVENT_STATUS_LABELS);
export const PIPELINE_STATUS_OPTIONS = Object.keys(PIPELINE_STATUS_LABELS);
export const PIPELINE_STAGE_OPTIONS = Object.keys(PIPELINE_STAGE_LABELS);

export function labelLookup(map: Record<string, string>, value: string | null | undefined): string {
  if (!value) return "—";
  return map[value] ?? value;
}

export function isPublishedEvent(event: Pick<AdminEvent, "status">): boolean {
  return event.status === "PUBLISHED";
}

export function uniqueEventValues(events: AdminEvent[], key: keyof AdminEvent): string[] {
  const values = new Set<string>();
  for (const event of events) {
    const value = event[key];
    if (typeof value === "string" && value.trim()) {
      values.add(value);
    }
  }
  return [...values].sort((a, b) => a.localeCompare(b, "es"));
}
