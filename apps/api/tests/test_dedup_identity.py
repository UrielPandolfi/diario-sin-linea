from datetime import datetime, timedelta, timezone
from math import sqrt

import pytest

from app.domain.enums import EntityType
from app.providers.fakes import FakeEmbeddingProvider, FakeStructuredLLM
from app.schemas import EventCreate
from app.schemas.detection import DedupDecision, EventCandidate, ExtractedEntity
from app.services.dedup_identity import compare_identity
from app.services.detection_service import DetectionService
from app.services.event_service import EventService
from tests.test_detection import _item, _source


_AR = timezone(timedelta(hours=-3))


def _facts(**changes):
    values = dict(
        event_type="anuncio_oficial",
        what_happened="El municipio anunció un programa de becas.",
        short_summary="Anuncio de becas municipales.",
        occurred_at=datetime(2026, 9, 14, 14, tzinfo=_AR),
        country_code="AR", province="Santa Fe", locality="Rosario",
        address_text="San Martín 100",
        entities=[ExtractedEntity(name="Municipalidad de Rosario", entity_type=EntityType.GOVERNMENT)],
    )
    values.update(changes)
    return EventCandidate(**values)


@pytest.mark.parametrize("left,right", [
    ("Av. Pellegrini y calle Corrientes", "Corrientes / Avenida Pellegrini"),
    ("Bv. Oroño & Córdoba", "calle Córdoba esquina de Boulevard Oroño"),
    ("calle San Martín al 100", "  SAN MARTIN 100  "),
])
def test_structurally_equivalent_addresses_do_not_conflict(left, right):
    assert compare_identity(_facts(address_text=left), _facts(address_text=right)).conflicts == ()


@pytest.mark.parametrize("field,value,conflict", [
    ("address_text", "San Martín 200", "address"),
    ("locality", "Córdoba", "locality"),
    ("province", "Córdoba", "province"),
    ("country_code", "UY", "country_code"),
])
def test_explicit_location_conflicts_block_automatic_identity(field, value, conflict):
    result = compare_identity(_facts(), _facts(**{field: value}))
    assert result.conflicts == (conflict,)


@pytest.mark.parametrize("left,right", [
    ("Pellegrini y Corrientes", "Pellegrini 900"),
    ("Pellegrini", "Pellegrini y Corrientes"),
    ("Ruta 9", "Ruta 11"),
    (None, "San Martín 100"),
])
def test_incomplete_or_incomparable_addresses_are_unknown(left, right):
    assert compare_identity(_facts(address_text=left), _facts(address_text=right)).conflicts == ()


def test_different_complete_intersections_conflict():
    assert compare_identity(_facts(address_text="Pellegrini y Corrientes"),
                            _facts(address_text="Pellegrini y Oroño")).conflicts == ("address",)


@pytest.mark.parametrize("description", [
    "Un colectivo chocó contra una moto. Otro ómnibus colisionó con un automóvil.",
    "La intendenta anunció otro programa de becas.",
    "Un tribunal dictó sentencia en otra causa.",
])
def test_prose_does_not_create_structural_conflicts(description):
    assert compare_identity(_facts(), _facts(what_happened=description, short_summary=description)).conflicts == ()


@pytest.mark.parametrize("minutes,wording", [
    (30, "a las"), (120, "a las"), (240, "a las"),
    (240, "alrededor de las"), (1440, "a las"),
])
def test_times_without_structured_precision_do_not_veto_identity(minutes, wording):
    start = datetime(2026, 9, 14, 14, tzinfo=_AR)
    end = start + timedelta(minutes=minutes)
    left = _facts(occurred_at=start, what_happened=f"El municipio anunció becas {wording} {start:%H:%M}.")
    right = _facts(occurred_at=end, what_happened=f"El municipio anunció becas {wording} {end:%H:%M}.")
    assert compare_identity(left, right).conflicts == ()


def test_utc_storage_does_not_create_a_conflict_near_midnight():
    instant = datetime(2026, 9, 14, 23, 30, tzinfo=_AR)
    assert compare_identity(_facts(occurred_at=instant), _facts(occurred_at=instant.astimezone(timezone.utc))).conflicts == ()


def test_location_normalization_ignores_case_accents_and_spacing():
    left = _facts(locality="Córdoba")
    right = _facts(country_code="ar", province="  santa   fe ", locality="  CORDOBA ")
    assert compare_identity(left, right).conflicts == ()


def test_missing_fields_and_new_entities_do_not_contradict_known_facts():
    right = _facts(address_text=None, occurred_at=None, country_code=None, province=None, locality=None)
    right.entities.append(ExtractedEntity(name="Testigo nuevo", entity_type=EntityType.PERSON))
    result = compare_identity(_facts(), right)
    assert result.conflicts == ()


def _ranked_events(session, *, compatible_score: float, terra_chooses_conflict: bool):
    """Exercise real retrieval/scoring against two persisted Event fixtures."""
    source = _source(session)
    incoming = _item(session, source.id, url="https://incoming.test/new", title="Anuncio de becas", body="Anuncio de becas", content_hash="incoming")
    embedder = FakeEmbeddingProvider()
    embedder.mode = "high"  # Query vector (1, 0, ...), against explicit stored vectors.
    terra = FakeStructuredLLM()
    service = DetectionService(session, embeddings=embedder, dedup_llm=terra)
    event_service = EventService(session)
    stored = []
    for address, score in (("San Martín 200", 0.97), ("San Martín 100", compatible_score)):
        event = event_service.create(EventCreate(
            event_type="anuncio_oficial", title_internal="El municipio anunció un programa de becas.",
            short_summary="Anuncio de becas", country_code="AR", province="Santa Fe", locality="Rosario",
            address_text=address, started_at=datetime(2026, 9, 14, 14, tzinfo=_AR),
        ))
        service.events.upsert_embedding(event.id, [score, sqrt(1 - score ** 2)] + [0.0] * 1022, embedder.model)
        stored.append(event)
    session.flush()
    target = stored[0] if terra_chooses_conflict else stored[1]
    terra.responses["DedupDecision"] = DedupDecision(decision="EXISTING_EVENT", event_id=target.id, confidence=0.9)
    event, created, reason = service._resolve_event(incoming, _facts())
    return stored, event, created, reason, terra


def test_high_score_conflict_does_not_hide_a_compatible_runner_up(db_session):
    stored, event, created, reason, terra = _ranked_events(db_session, compatible_score=0.90, terra_chooses_conflict=False)
    assert event.id == stored[1].id and not created
    assert reason == "embedding_high:0.900"
    assert terra.calls == []


@pytest.mark.parametrize("chooses_conflict", [False, True])
def test_terra_cannot_restore_a_candidate_rejected_for_conflict(db_session, chooses_conflict):
    stored, event, created, reason, terra = _ranked_events(db_session, compatible_score=0.80, terra_chooses_conflict=chooses_conflict)
    assert terra.calls == ["DedupDecision"]
    assert str(stored[0].id) not in terra.user_prompts[0]
    assert str(stored[1].id) in terra.user_prompts[0]
    if chooses_conflict:
        assert created and reason == "terra_new"
        assert event.id not in {row.id for row in stored}
    else:
        assert not created and reason == "terra_existing" and event.id == stored[1].id
