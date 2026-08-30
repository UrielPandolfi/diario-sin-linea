from app.core.source_snippet import select_source_snippet


def test_snippet_returns_short_text_untouched() -> None:
    text = "Lead corto."
    assert select_source_snippet(text) == text


def test_snippet_prefers_lead_numbers_and_place_within_budget() -> None:
    filler = "Opinión de color sin dato útil. " * 40
    lead = "Un colectivo chocó en Pellegrini."
    numbers = "Hay 6 heridos confirmados, entre ellos dos menores."
    place = "El choque fue en Rosario, a metros de la terminal."
    late = "El intendente prometió más semáforos el año que viene."
    text = "\n\n".join([lead, filler, numbers, place, late])
    snippet = select_source_snippet(
        text,
        budget=400,
        entity_names=["colectivo"],
        locality="Rosario",
    )
    assert lead in snippet
    assert "6 heridos" in snippet
    assert "Rosario" in snippet
    assert filler.strip()[:40] not in snippet or len(snippet) <= 400
    assert len(snippet) <= 400


def test_snippet_falls_back_to_truncate_without_paragraphs() -> None:
    blob = "x" * 2000
    snippet = select_source_snippet(blob, budget=150)
    assert snippet == blob[:150]
