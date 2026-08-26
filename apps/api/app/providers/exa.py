from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.providers.base import SearchHit, SearchQuery

EXA_SEARCH_URL = "https://api.exa.ai/search"
_DEFAULT_TIMEOUT = 20.0
_FRESHNESS_DAYS = {
    "pd": 1,
    "pw": 7,
    "pm": 31,
    "py": 365,
}


def _clamp_num_results(count: int) -> int:
    return max(1, min(int(count), 100))


def _start_published_date(query: SearchQuery) -> str | None:
    if query.since is not None:
        return query.since.astimezone(timezone.utc).date().isoformat()
    freshness = (query.freshness or "").strip().lower()
    days = _FRESHNESS_DAYS.get(freshness)
    if days is None:
        return None
    return (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()


def _end_published_date(query: SearchQuery) -> str | None:
    if query.until is None:
        return None
    return query.until.astimezone(timezone.utc).date().isoformat()


def _snippet_from_result(row: dict[str, Any]) -> str | None:
    highlights = row.get("highlights")
    if isinstance(highlights, list):
        parts = [str(part).strip() for part in highlights if part]
        if parts:
            return " ".join(parts)
    text = row.get("text")
    if isinstance(text, str) and text.strip():
        return text.strip()[:500]
    summary = row.get("summary")
    if isinstance(summary, str) and summary.strip():
        return summary.strip()
    return None


def _build_payload(query: SearchQuery) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "query": query.text,
        "type": "auto",
        "numResults": _clamp_num_results(query.count),
        "contents": {"highlights": True},
    }
    start = _start_published_date(query)
    if start:
        payload["startPublishedDate"] = start
    end = _end_published_date(query)
    if end:
        payload["endPublishedDate"] = end
    return payload


def normalize_exa_results(payload: Any) -> list[SearchHit]:
    if not isinstance(payload, dict):
        raise ValueError("Respuesta inválida de Exa: se esperaba un objeto JSON")
    results = payload.get("results")
    if results is None:
        return []
    if not isinstance(results, list):
        raise ValueError("Respuesta inválida de Exa: results no es una lista")
    hits: list[SearchHit] = []
    for row in results:
        if not isinstance(row, dict):
            continue
        url = row.get("url")
        if not url or not isinstance(url, str):
            continue
        title = row.get("title")
        hits.append(
            SearchHit(
                title=title if isinstance(title, str) else "",
                url=url,
                snippet=_snippet_from_result(row),
            )
        )
    return hits


class ExaSearchProvider:
    def __init__(self, *, api_key: str, timeout: float = _DEFAULT_TIMEOUT) -> None:
        self.api_key = api_key
        self.timeout = timeout

    def search(self, query: SearchQuery) -> list[SearchHit]:
        payload = _build_payload(query)
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(
                EXA_SEARCH_URL,
                json=payload,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                },
            )
            response.raise_for_status()
            try:
                body = response.json()
            except ValueError as exc:
                raise ValueError("Respuesta inválida de Exa: JSON no parseable") from exc
        return normalize_exa_results(body)
