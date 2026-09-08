from __future__ import annotations

import re
from typing import Any

from app.schemas.writing import (
    ArticleContext,
    ArticleDraft,
    ArticleDraftBlock,
    ArticleDraftSegment,
    PersistedBodyBlock,
    PersistedBodySegment,
)

_HTML_TAG = re.compile(r"<[^>]+>")
_CLAIM_REF = re.compile(r"^C\d+$")
_UUID = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


class ArticleDraftValidationError(ValueError):
    pass


def plain_article_draft(headline: str, summary: str, body: str) -> ArticleDraft:
    paragraphs = [part.strip() for part in body.split("\n\n") if part.strip()]
    if not paragraphs:
        paragraphs = [body.strip() or " "]
    return ArticleDraft(
        headline=headline,
        summary=summary,
        body_blocks=[
            ArticleDraftBlock(
                type="paragraph",
                segments=[ArticleDraftSegment(text=paragraph, claim_refs=[])],
            )
            for paragraph in paragraphs
        ],
    )


def annotated_article_draft(
    headline: str,
    summary: str,
    paragraphs: list[list[tuple[str, list[str]]]],
) -> ArticleDraft:
    if not paragraphs:
        raise ValueError("paragraphs vacío")
    return ArticleDraft(
        headline=headline,
        summary=summary,
        body_blocks=[
            ArticleDraftBlock(
                type="paragraph",
                segments=[
                    ArticleDraftSegment(text=text, claim_refs=refs) for text, refs in segments
                ],
            )
            for segments in paragraphs
        ],
    )


def render_article_body(blocks: list[ArticleDraftBlock] | list[PersistedBodyBlock] | list[dict]) -> str:
    paragraphs: list[str] = []
    for block in blocks:
        if isinstance(block, dict):
            segments = block.get("segments") or []
            text = "".join(str(segment.get("text") or "") for segment in segments)
        else:
            text = "".join(segment.text for segment in block.segments)
        stripped = text.strip()
        if stripped:
            paragraphs.append(stripped)
    return "\n\n".join(paragraphs)


def context_claim_ref_map(context: ArticleContext) -> dict[str, str]:
    if context.claim_refs:
        return dict(context.claim_refs)
    mapping: dict[str, str] = {}
    for bucket in (
        context.confirmed_claims,
        context.single_source_claims,
        context.conflicting_claims,
        context.uncertain_claims,
        context.disproven_claims,
        context.outdated_claims,
    ):
        for claim in bucket:
            mapping[claim.ref] = claim.id
    return mapping


def _validate_segment_text(text: str) -> None:
    if not text or not text.strip():
        raise ArticleDraftValidationError("segmento vacío")
    if _HTML_TAG.search(text):
        raise ArticleDraftValidationError("los segmentos deben ser texto plano, sin HTML")


def resolve_article_draft(
    draft: ArticleDraft,
    *,
    claim_ref_map: dict[str, str],
) -> tuple[str, list[dict[str, Any]]]:
    if not draft.body_blocks:
        raise ArticleDraftValidationError("body_blocks vacío")
    persisted: list[PersistedBodyBlock] = []
    for block in draft.body_blocks:
        if block.type != "paragraph":
            raise ArticleDraftValidationError(f"tipo de bloque no soportado: {block.type}")
        if not block.segments:
            raise ArticleDraftValidationError("párrafo sin segmentos")
        segments: list[PersistedBodySegment] = []
        for segment in block.segments:
            _validate_segment_text(segment.text)
            claim_ids: list[str] = []
            for raw in segment.claim_refs:
                ref = (raw or "").strip()
                if not ref:
                    raise ArticleDraftValidationError("claim_ref vacío")
                if _UUID.match(ref):
                    raise ArticleDraftValidationError("claim_refs debe usar C1/C2, no UUIDs")
                if not _CLAIM_REF.match(ref) or ref not in claim_ref_map:
                    raise ArticleDraftValidationError(f"claim_ref inexistente: {ref}")
                claim_id = claim_ref_map[ref]
                if claim_id not in claim_ids:
                    claim_ids.append(claim_id)
            segments.append(PersistedBodySegment(text=segment.text, claim_ids=claim_ids))
        persisted.append(PersistedBodyBlock(type="paragraph", segments=segments))
    body = render_article_body(persisted)
    if not body.strip():
        raise ArticleDraftValidationError("body derivado vacío")
    return body, [block.model_dump(mode="json") for block in persisted]


def split_body_paragraphs(body: str) -> list[str]:
    paragraphs = [part.strip() for part in (body or "").split("\n\n") if part.strip()]
    if paragraphs:
        return paragraphs
    stripped = (body or "").strip()
    return [stripped] if stripped else []


def block_plain_text(block: dict | PersistedBodyBlock) -> str:
    if isinstance(block, dict):
        segments = block.get("segments") or []
        return "".join(str(segment.get("text") or "") for segment in segments).strip()
    return "".join(segment.text for segment in block.segments).strip()


def claim_ids_in_body_blocks(blocks: list | dict | None) -> set[str]:
    ids: set[str] = set()
    if not isinstance(blocks, list):
        return ids
    for block in blocks:
        if not isinstance(block, dict):
            continue
        for segment in block.get("segments") or []:
            if not isinstance(segment, dict):
                continue
            for claim_id in segment.get("claim_ids") or []:
                text = str(claim_id).strip()
                if text:
                    ids.add(text)
    return ids


def merge_editorial_body_blocks(live_blocks: list | dict | None, new_body: str) -> tuple[str, list[dict[str, Any]]]:
    paragraphs = split_body_paragraphs(new_body)
    if not paragraphs:
        raise ArticleDraftValidationError("body derivado vacío")
    unused: list[dict[str, Any]] = []
    if isinstance(live_blocks, list):
        unused = [block for block in live_blocks if isinstance(block, dict)]
    merged: list[dict[str, Any]] = []
    for paragraph in paragraphs:
        match_index = next(
            (index for index, block in enumerate(unused) if block_plain_text(block) == paragraph),
            None,
        )
        if match_index is not None:
            merged.append(unused.pop(match_index))
        else:
            merged.append({"type": "paragraph", "segments": [{"text": paragraph, "claim_ids": []}]})
    body = render_article_body(merged)
    if not body.strip():
        raise ArticleDraftValidationError("body derivado vacío")
    return body, merged
