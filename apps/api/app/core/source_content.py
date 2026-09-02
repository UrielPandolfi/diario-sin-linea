from __future__ import annotations

from typing import Any

from app.core.text import normalize_name


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
