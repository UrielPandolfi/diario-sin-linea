from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest

from app.core.prompts import load_prompt
from app.providers.fakes import FakeStructuredLLM
from app.schemas.detection import EventCandidate
from app.services.detection_service import DetectionService
from app.services.editorial_gate import apply_canonical_location


def _candidate(**changes):
    values = dict(what_happened="El Gobierno anunció una medida.", short_summary="Anuncio oficial.")
    values.update(changes)
    return EventCandidate(**values)


@pytest.mark.parametrize("placeholder", ["null", " NONE ", "undefined", "nil", "n/a", "unknown", "", "   "])
def test_optional_placeholders_become_json_null(placeholder):
    fields = ("country_code", "province", "locality", "neighborhood", "address_text",
              "editorial_reason", "gate_reason", "occurred_at", "latitude", "longitude")
    candidate = _candidate(**{name: placeholder for name in fields})
    assert all(candidate.model_dump(mode="json")[name] is None for name in fields)


def test_optional_values_are_trimmed_without_removing_real_text_or_zero_coordinates():
    candidate = _candidate(province=" Buenos Aires ", locality=" La Plata ",
                           address_text=" Calle Sin Nombre 123 ", latitude=0, longitude=0)
    assert (candidate.province, candidate.locality, candidate.address_text) == (
        "Buenos Aires", "La Plata", "Calle Sin Nombre 123",
    )
    assert candidate.latitude == candidate.longitude == 0


@pytest.mark.parametrize("province,locality", [
    ("Buenos Aires", "Ciudad Autónoma de Buenos Aires"),
    ("Ciudad Autónoma de Buenos Aires", "null"),
    ("CABA", "Buenos Aires"),
    (None, "c.a.b.a."),
])
def test_explicit_caba_has_one_canonical_representation(province, locality):
    candidate = apply_canonical_location(_candidate(province=province, locality=locality))
    assert (candidate.country_code, candidate.province, candidate.locality) == (
        "AR", "Ciudad Autónoma de Buenos Aires", "Ciudad Autónoma de Buenos Aires",
    )
    before = candidate.model_dump()
    assert apply_canonical_location(candidate).model_dump() == before


@pytest.mark.parametrize("province,locality", [
    ("Buenos Aires", "La Plata"),
    ("Buenos Aires", "Mar del Plata"),
    ("Buenos Aires", None),
    (None, "Buenos Aires"),
])
def test_buenos_aires_province_and_ambiguous_name_are_not_caba(province, locality):
    candidate = apply_canonical_location(_candidate(province=province, locality=locality))
    assert (candidate.province, candidate.locality) == (province, locality)


def test_caba_normalization_keeps_neighborhood_separate():
    candidate = apply_canonical_location(_candidate(province="CABA", locality=None, neighborhood="Palermo"))
    assert candidate.locality == "Ciudad Autónoma de Buenos Aires"
    assert candidate.neighborhood == "Palermo"


@pytest.mark.parametrize("value", ["2026-09-14", " 2026-09-14 ", date(2026, 9, 14)])
def test_date_without_time_does_not_become_a_midnight_instant(value):
    assert _candidate(occurred_at=value).occurred_at is None


@pytest.mark.parametrize("value", ["2026-09-14T14:00:00-03:00", "2026-09-14T00:00:00-03:00"])
def test_explicit_instant_is_preserved_including_explicit_midnight(value):
    assert _candidate(occurred_at=value).occurred_at == datetime.fromisoformat(value)


@pytest.mark.parametrize("title,body,province,locality", [
    ("Anuncio oficial", "Este lunes el ministro presentó la medida en la Ciudad Autónoma de Buenos Aires.",
     "Buenos Aires", "Ciudad Autónoma de Buenos Aires"),
    ("Nueva medida económica", "La Ciudad Autónoma de Buenos Aires fue sede de la presentación ministerial este lunes.",
     "Ciudad Autónoma de Buenos Aires", "null"),
])
def test_extraction_path_normalizes_both_caba_representations_before_return(
    title, body, province, locality,
):
    candidate = _candidate(province=province, locality=locality, occurred_at="2026-09-14")
    llm = FakeStructuredLLM({"EventCandidate": candidate})
    service = DetectionService(None, light_llm=llm)
    item = SimpleNamespace(title=title, clean_text=body, raw_text=None,
                           url="https://normalization.test/anuncio",
                           published_at=datetime(2026, 9, 14, 18, 30, tzinfo=timezone.utc))
    result, metadata = service._extract_candidate(item)
    assert result.province == result.locality == "Ciudad Autónoma de Buenos Aires"
    assert result.occurred_at is None
    assert metadata == {}


def test_prompt_distinguishes_jurisdictions_and_forbids_publication_time_as_event_time():
    prompt = load_prompt("event_extraction.md")
    assert "null JSON (sin comillas)" in prompt
    assert "CABA / Ciudad Autónoma de Buenos Aires es una jurisdicción distinta de la Provincia de Buenos Aires" in prompt
    assert "La marca Publicado es metadata de la publicación, no la hora del suceso" in prompt
    assert 'No completes una fecha con 00:00:00 ni con la hora de publicación' in prompt
    assert 'hora aproximada, usá null' in prompt
    assert 'occurred_at="2026-09-14T14:00:00-03:00", province="Buenos Aires", locality="La Plata"' in prompt
