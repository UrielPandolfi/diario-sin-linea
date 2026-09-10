export type ArticleSource = {
  name: string | null;
  domain: string | null;
  url: string | null;
  title: string | null;
};

export type EventCard = {
  slug: string;
  public_id: string;
  headline: string;
  summary: string;
  locality: string | null;
  province: string | null;
  published_at: string | null;
  updated_at: string | null;
  sources: ArticleSource[];
  score?: number;
};

export type ArticleBodySegment = {
  text: string;
  claim_ids: string[];
};

export type ArticleBodyBlock = {
  type: "paragraph";
  segments: ArticleBodySegment[];
};

export type FalseAssertion = {
  source_item_id: string;
  source_name: string;
  source_url: string | null;
  excerpt: string;
};

export type ClaimEvidenceDetail = {
  evidence_type: string;
  stance: string;
  name: string | null;
  url: string | null;
};

export type ClaimCardPresentation = {
  verification_label: string;
  limitation: string | null;
  coverage: string;
  explanation: string | null;
  evidence_detail: ClaimEvidenceDetail[];
  basis_known: boolean;
  demotion: string | null;
  documents_consulted: number | null;
  documents_reporting: number | null;
  known_independent_count: number | null;
  unknown_group_count: number | null;
  reprint_collapsed_count?: number | null;
  document_noun?: string;
};

export type ArticleClaim = {
  id: string;
  canonical_text: string;
  status: string;
  importance: string;
  source_count: number;
  evidence_count: number;
  editorial_labels?: string[];
  false_assertions?: FalseAssertion[];
  presentation?: ClaimCardPresentation;
  verification: {
    unresolved?: boolean | null;
    status_after?: string | null;
    reason?: string | null;
  } | null;
};

export type Article = EventCard & {
  body: string;
  body_blocks?: ArticleBodyBlock[] | null;
  hero_image_url: string | null;
  claims?: ArticleClaim[];
  published_version?: number | null;
  article_id?: string;
  notices?: ArticleNotice[];
  history?: ArticleHistoryItem[];
};

export type ArticleNotice = {
  kind: string;
  notice: string;
  occurred_at: string | null;
  show_near_title: boolean;
};

export type ArticleHistoryItem = {
  type: string;
  occurred_at: string | null;
  notice: string | null;
  headline: string | null;
};

export type CaseFollowUp = {
  public_code: string;
  status: string;
  outcome: string | null;
  public_resolution: string | null;
  reason: string;
  message: string;
  created_at: string | null;
  reviewing_at: string | null;
  resolved_at: string | null;
  article: { slug: string; headline: string } | null;
};

export type CaseCreateResponse = {
  public_code: string;
  follow_up_url: string;
};

export type NowItem = {
  occurred_at: string | null;
  locality: string | null;
  headline: string;
  slug: string;
  public_id: string;
};

export type CursorPage = {
  items: EventCard[];
  next_cursor: string | null;
};

export type NowResponse = {
  items: NowItem[];
};

export type NearbyResponse = {
  items: EventCard[];
};

export type SearchResponse = {
  items: EventCard[];
  query: string;
};

export type LocalitiesResponse = {
  items: string[];
};

export type FeedScope = "main" | "local" | "argentina";
