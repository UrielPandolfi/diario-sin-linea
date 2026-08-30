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

export type Article = EventCard & {
  body: string;
  hero_image_url: string | null;
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
