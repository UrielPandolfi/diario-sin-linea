from uuid import uuid4

import pytest

from app.core.article_body import (
    ArticleDraftValidationError,
    annotated_article_draft,
    context_claim_ref_map,
    plain_article_draft,
    render_article_body,
    resolve_article_draft,
)
from app.schemas.writing import ArticleContext, ContextEventStub


def test_plain_draft_derives_paragraphs_and_empty_refs() -> None:
    draft = plain_article_draft("Titular", "Resumen", "Uno.\n\nDos.")
    assert len(draft.body_blocks) == 2
    assert draft.body_blocks[0].segments[0].claim_refs == []
    assert render_article_body(draft.body_blocks) == "Uno.\n\nDos."


def test_resolve_maps_c1_and_rejects_unknown_or_uuid() -> None:
    claim_id = str(uuid4())
    mapping = {"C1": claim_id}
    draft = annotated_article_draft(
        "Titular",
        "Resumen",
        paragraphs=[
            [("Narrativa sin cifra.", [])],
            [("El aumento es del 12,22%.", ["C1"])],
        ],
    )
    body, blocks = resolve_article_draft(draft, claim_ref_map=mapping)
    assert body == "Narrativa sin cifra.\n\nEl aumento es del 12,22%."
    assert blocks[0]["segments"][0]["claim_ids"] == []
    assert blocks[1]["segments"][0]["claim_ids"] == [claim_id]
    assert "claim_refs" not in blocks[1]["segments"][0]

    with pytest.raises(ArticleDraftValidationError, match="inexistente"):
        resolve_article_draft(
            annotated_article_draft("T", "S", paragraphs=[[("x", ["C99"])]]),
            claim_ref_map=mapping,
        )
    with pytest.raises(ArticleDraftValidationError, match="UUID"):
        resolve_article_draft(
            annotated_article_draft("T", "S", paragraphs=[[("x", [claim_id])]]),
            claim_ref_map=mapping,
        )
    with pytest.raises(ArticleDraftValidationError, match="HTML"):
        resolve_article_draft(
            annotated_article_draft("T", "S", paragraphs=[[("<b>x</b>", [])]]),
            claim_ref_map=mapping,
        )


def test_merge_editorial_keeps_exact_blocks_and_strips_changed() -> None:
    from app.core.article_body import merge_editorial_body_blocks

    claim_id = str(uuid4())
    live = [
        {"type": "paragraph", "segments": [{"text": "Párrafo estable.", "claim_ids": [claim_id]}]},
        {"type": "paragraph", "segments": [{"text": "Párrafo a editar.", "claim_ids": [claim_id]}]},
    ]
    body, blocks = merge_editorial_body_blocks(live, "Párrafo estable.\n\nPárrafo corregido.")
    assert body == "Párrafo estable.\n\nPárrafo corregido."
    assert blocks[0]["segments"][0]["claim_ids"] == [claim_id]
    assert blocks[1]["segments"][0]["claim_ids"] == []


def test_context_claim_ref_map_prefers_explicit_index() -> None:
    context = ArticleContext(
        event=ContextEventStub(
            event_id=str(uuid4()),
            event_type="anuncio_oficial",
            working_title="Aumento FFAA",
        ),
        claim_refs={"C1": "aaa", "C2": "bbb"},
    )
    assert context_claim_ref_map(context) == {"C1": "aaa", "C2": "bbb"}
