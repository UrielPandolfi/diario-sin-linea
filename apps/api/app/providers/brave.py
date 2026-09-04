from datetime import datetime, timezone

import httpx

from app.providers.base import SearchHit, SearchQuery


class BraveSearchProvider:
    def __init__(self, *, api_key: str) -> None:
        self.api_key = api_key

    def search(self, query: SearchQuery) -> list[SearchHit]:
        params: dict[str, str | int] = {"q": query.text, "count": query.count}
        freshness = query.freshness
        if not freshness and query.since and query.until:
            freshness = f"{query.since.date()}to{query.until.date()}"
        elif not freshness and query.since:
            end = query.until.date() if query.until else datetime.now(timezone.utc).date()
            freshness = f"{query.since.date()}to{end}"
        if freshness:
            params["freshness"] = freshness
        with httpx.Client(timeout=20.0) as client:
            response = client.get(
                "https://api.search.brave.com/res/v1/web/search",
                params=params,
                headers={
                    "Accept": "application/json",
                    "X-Subscription-Token": self.api_key,
                },
            )
            response.raise_for_status()
        results = response.json().get("web", {}).get("results", [])
        hits: list[SearchHit] = []
        for row in results:
            url = row.get("url")
            if not url:
                continue
            hits.append(
                SearchHit(
                    title=row.get("title") or "",
                    url=url,
                    snippet=row.get("description"),
                )
            )
        return hits
