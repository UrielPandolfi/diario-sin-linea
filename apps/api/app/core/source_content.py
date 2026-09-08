from __future__ import annotations

from typing import Any

from app.core.text import normalize_name

BODY_SOURCE_EXTRACTED_HTML = "extracted_html"
BODY_SOURCE_RSS_SUMMARY = "rss_summary"
BODY_SOURCE_SEARCH_SNIPPET = "search_snippet"
BODY_SOURCE_TITLE_ONLY = "title_only"
BODY_SOURCE_UNKNOWN = "unknown"

KNOWN_BODY_SOURCES = {
    BODY_SOURCE_EXTRACTED_HTML,
    BODY_SOURCE_RSS_SUMMARY,
    BODY_SOURCE_SEARCH_SNIPPET,
    BODY_SOURCE_TITLE_ONLY,
    BODY_SOURCE_UNKNOWN,
}


def is_extracted_body(text: str | None, title: str | None = None) -> bool:
    body = (text or "").strip()
    if not body:
        return False
    folded_body = normalize_name(body)
    if not folded_body:
        return False
    folded_title = normalize_name(title or "")
    if folded_title and folded_body == folded_title:
        return False
    return True


def has_extracted_body(item: Any) -> bool:
    return is_extracted_body(
        getattr(item, "clean_text", None),
        getattr(item, "title", None),
    )


def body_source_from_item(item: Any) -> str:
    meta = getattr(item, "metadata_json", None) or {}
    if not isinstance(meta, dict):
        return BODY_SOURCE_UNKNOWN
    value = meta.get("body_source")
    if value in KNOWN_BODY_SOURCES:
        return str(value)
    return BODY_SOURCE_UNKNOWN


def merge_item_metadata(item: Any, **fields: Any) -> dict[str, Any]:
    meta = dict(getattr(item, "metadata_json", None) or {})
    for key, value in fields.items():
        if value is not None:
            meta[key] = value
    item.metadata_json = meta
    return meta
