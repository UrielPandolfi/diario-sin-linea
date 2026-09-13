"""Preserve attributed speech and temporal magnitudes without asserting their truth."""
from __future__ import annotations

import re

from app.core.text import excerpt_in_source
from app.schemas.claims import ExtractedClaim

_SAID = re.compile(r"\b(reconoci[oó]|dijo|afirm[oó]|declar[oó]|sostuvo|se[nñ]al[oó]|asegur[oó])\s+que\b", re.I)
_TRAJECTORY = re.compile(r"\bdesde\b[^.\n]*?\d+(?:[.,]\d+)?\s*%[^.\n]*?\bhasta\b[^.\n]*?\d+(?:[.,]\d+)?\s*%", re.I)


def attributed_statement(text: str) -> bool:
    return bool(_SAID.search(text or ""))


def temporal_comparison(text: str) -> bool:
    return bool(_TRAJECTORY.search(text or ""))


def preserve_extracted_meaning(raw: ExtractedClaim, sources: list) -> ExtractedClaim:
    text = raw.canonical_text
    trajectory = _TRAJECTORY.search(text)
    # Recover an omitted relative anchor only from a literal, cited source passage
    # with the same endpoints. Never infer an inauguration date from world knowledge.
    if trajectory:
        values = re.findall(r"\d+(?:[.,]\d+)?\s*%", trajectory.group())
        for ev in raw.evidence:
            if not 1 <= ev.source_ref <= len(sources):
                continue
            source = sources[ev.source_ref - 1]
            if not ev.excerpt or not excerpt_in_source(ev.excerpt, source.clean_text):
                continue
            original = _TRAJECTORY.search(ev.excerpt)
            if original and re.findall(r"\d+(?:[.,]\d+)?\s*%", original.group()) == values:
                text = text[:trajectory.start()] + original.group() + text[trajectory.end():]
                break
    updates = {"canonical_text": text}
    said = _SAID.search(text)
    if said:
        speaker = text[:said.start()].strip()
        if speaker.lower().startswith("según ") and "," in speaker:
            speaker = speaker.rsplit(",", 1)[-1].strip()
        # Attribution is the proposition; its economic content is not its subject.
        updates.update(claim_type="declaracion", subject=speaker,
                       predicate=said.group().strip(), object_text=text[said.end():].strip(),
                       normalized_value=None, unit=None)
    elif trajectory:
        # Full trajectory participates in identity; a terminal scalar loses the origin.
        updates.update(normalized_value=None, object_text=text)
    return raw.model_copy(update=updates)


def material_query(claim) -> str | None:
    text = claim.canonical_text or ""
    if attributed_statement(text) or temporal_comparison(text):
        return text.strip()
    return None


def split_attributed_content(raw: ExtractedClaim) -> list[ExtractedClaim]:
    """Expand the existing extractor's semantic distinction, without inferring truth."""
    content = raw.factual_content
    attribution = raw.model_copy(update={"factual_content": None})
    if content is None or not (attributed_statement(raw.canonical_text) or raw.claim_type == "declaracion"):
        return [attribution]
    if attributed_statement(content.canonical_text) or content.claim_type == "declaracion":
        return [attribution]
    # These publications report the fact; resolution still checks independence.
    factual = ExtractedClaim(**content.model_dump(), evidence=[ev.model_copy() for ev in raw.evidence])
    return [attribution, factual]
