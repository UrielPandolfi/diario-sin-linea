from __future__ import annotations

import re

from app.core.text import normalize_name

SNIPPET_CHARS = 1500

_DATE_RE = re.compile(
    r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b"
    r"|\b\d{1,2}:\d{2}\b"
    r"|\b(?:lunes|martes|miércoles|miercoles|jueves|viernes|sábado|sabado|domingo)\b"
    r"|\b(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\b",
    re.IGNORECASE,
)
_DIGIT_RE = re.compile(r"\d")


def split_paragraphs(text: str) -> list[str]:
    parts = [part.strip() for part in re.split(r"\n\s*\n+", text.strip()) if part.strip()]
    if len(parts) <= 1:
        parts = [part.strip() for part in text.split("\n") if part.strip()]
    return parts or ([text.strip()] if text.strip() else [])


def _para_score(
    index: int,
    para: str,
    *,
    entity_needles: list[str],
    place_needles: list[str],
) -> int:
    score = 0
    if index == 0:
        score += 100
    elif index == 1:
        score += 40
    if _DIGIT_RE.search(para):
        score += 30
    if _DATE_RE.search(para):
        score += 25
    folded = normalize_name(para)
    if any(needle and needle in folded for needle in entity_needles):
        score += 35
    if any(needle and needle in folded for needle in place_needles):
        score += 25
    return score


def select_source_snippet(
    text: str,
    *,
    budget: int = SNIPPET_CHARS,
    entity_names: list[str] | tuple[str, ...] = (),
    locality: str | None = None,
    address: str | None = None,
) -> str:
    """Hasta `budget` chars: lead + párrafos con cifras, fechas, entidades o lugar."""
    cleaned = (text or "").strip()
    if not cleaned:
        return ""
    if len(cleaned) <= budget:
        return cleaned
    paragraphs = split_paragraphs(cleaned)
    if len(paragraphs) <= 1:
        return cleaned[:budget]

    entity_needles = [normalize_name(name) for name in entity_names if name]
    place_needles = [normalize_name(part) for part in (locality, address) if part]
    scores = [
        _para_score(index, para, entity_needles=entity_needles, place_needles=place_needles)
        for index, para in enumerate(paragraphs)
    ]

    chosen: list[int] = []
    used = 0
    lead = paragraphs[0]
    if len(lead) > budget:
        return lead[:budget]
    chosen.append(0)
    used = len(lead)

    ranked = sorted(range(1, len(paragraphs)), key=lambda index: (-scores[index], index))
    for index in ranked:
        extra = 2
        size = extra + len(paragraphs[index])
        if used + size > budget:
            continue
        chosen.append(index)
        used += size
    chosen.sort()
    return "\n\n".join(paragraphs[index] for index in chosen)
