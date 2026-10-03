from datetime import datetime, timezone

import httpx

from app.providers.base import SearchHit, SearchQuery


class BraveSearchProvider:
    def __init__(self, *, api_key: str) -> None:
        self.api_key = api_key
        self._attempt = 0

    def search(self, query: SearchQuery) -> list[SearchHit]:
        from app.services.search_cache import execute_cached_search

        params = self._params(query)
        return execute_cached_search(
            provider="brave",
            parameters=params,
            fetch=lambda: self._search_once(params),
        )

    def _params(self, query: SearchQuery) -> dict[str, str | int]:
        params: dict[str, str | int] = {"q": query.text, "count": query.count}
        if query.include_domains:
            sites = " OR ".join(f"site:{domain}" for domain in query.include_domains)
            params["q"] = f"{query.text} ({sites})"
        freshness = query.freshness
        if not freshness and query.since and query.until:
            freshness = f"{query.since.date()}to{query.until.date()}"
        elif not freshness and query.since:
            end = query.until.date() if query.until else datetime.now(timezone.utc).date()
            freshness = f"{query.since.date()}to{end}"
        if freshness:
            params["freshness"] = freshness
        return params

    def _search_once(self, params: dict[str, str | int]) -> list[SearchHit]:
        import time

        from app.services.usage_recorder import record_llm_usage

        self._attempt += 1
        started = time.perf_counter()
        try:
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
                body = response.json()
        except Exception:
            record_llm_usage(
                provider="brave",
                model="search",
                call_kind="search",
                failed=True,
                usage_reported=False,
                duration_ms=int((time.perf_counter() - started) * 1000),
                attempt_index=self._attempt,
                request_options={"parameters": params},
            )
            raise
        record_llm_usage(
            provider="brave",
            model="search",
            call_kind="search",
            usage_reported=True,
            duration_ms=int((time.perf_counter() - started) * 1000),
            attempt_index=self._attempt,
            request_options={"parameters": params},
        )
        results = body.get("web", {}).get("results", [])
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
