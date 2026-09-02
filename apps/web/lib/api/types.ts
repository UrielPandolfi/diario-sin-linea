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

export type ArticleClaim = {
  id: string;
  canonical_text: string;
  status: string;
  importance: string;
  source_count: number;
  evidence_count: number;
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
