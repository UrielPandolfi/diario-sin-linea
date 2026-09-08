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

export type ArticleClaim = {
  id: string;
  canonical_text: string;
  status: string;
  importance: string;
  source_count: number;
  evidence_count: number;
  editorial_labels?: string[];
  false_assertions?: FalseAssertion[];
  verification: {
    status_after: string | null;
    unresolved: boolean | null;
    reason: string | null;
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
