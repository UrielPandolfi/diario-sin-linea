from types import SimpleNamespace

from app.core.source_content import has_extracted_body, is_extracted_body


def test_empty_clean_text_is_not_body() -> None:
    assert has_extracted_body(SimpleNamespace(clean_text=None, title="Homicidio")) is False
    assert has_extracted_body(SimpleNamespace(clean_text="  ", title="Homicidio")) is False
    assert is_extracted_body(None, "Homicidio") is False


def test_title_copied_into_clean_text_is_not_body() -> None:
    title = "Un colectivo chocó contra un auto en Pellegrini y Corrientes"
    assert has_extracted_body(SimpleNamespace(clean_text=title, title=title)) is False
    assert has_extracted_body(SimpleNamespace(clean_text=title.upper(), title=title)) is False


def test_short_official_release_distinct_from_title_is_body() -> None:
    item = SimpleNamespace(
        title="Comunicado",
        clean_text="El municipio suspende el servicio de agua hasta las 18.",
    )
    assert has_extracted_body(item) is True


def test_rss_summary_distinct_from_title_is_body() -> None:
    item = SimpleNamespace(
        title="Homicidio en Ayacucho 4100",
        clean_text="La Policía confirmó un homicidio en barrio Alvear.",
    )
    assert has_extracted_body(item) is True
