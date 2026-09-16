"""Controlled DetectionService evaluation; no real provider calls.

The original editorial gate rejects these ordinary crashes. Tests that isolate
dedup explicitly override only its allow/reject result, after real normalization.
Unit vectors exercise stated similarity ranges, not Voyage's semantic accuracy.
"""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from math import sqrt

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.domain.enums import EntityType, IngestionMethod
from app.models import Event, EventSource, PipelineRun, SourceItem
from app.providers.fakes import FakeEmbeddingProvider, FakeStructuredLLM
from app.schemas import SourceCreate, SourceItemCreate
from app.schemas.detection import DedupDecision, EditorialTopic, EventCandidate, ExtractedEntity
from app.services.detection_service import DetectionService, embedding_text
from app.services.editorial_gate import evaluate_editorial_gate
from app.services.source_item_service import SourceItemService
from app.services.source_service import SourceService


_TEXTS = {
    "A": (
        "Un colectivo chocó contra un automóvil en avenida Pellegrini y Corrientes este lunes por la tarde. Seis personas resultaron heridas.",
        "Seis heridos dejó una colisión entre un ómnibus y un auto en la esquina de Corrientes y Pellegrini. Ocurrió durante la tarde del lunes.",
    ),
    "B": (
        "Dos colectivos chocaron en Pellegrini y Corrientes.",
        "Seis personas resultaron heridas en el choque entre dos colectivos ocurrido en Pellegrini y Corrientes.",
    ),
    "C": (
        "Un colectivo chocó contra un auto en Pellegrini y Corrientes a las 14:00.",
        "Un colectivo chocó contra una moto en Pellegrini y Oroño a las 18:00.",
    ),
    "D": (
        "Un colectivo chocó contra un auto en avenida Pellegrini durante la tarde del lunes.",
        "Una colisión entre un ómnibus y un vehículo dejó heridos en el centro de Rosario el lunes por la tarde.",
    ),
}
_AR = timezone(timedelta(hours=-3))


def _candidates(case: str, *, include_city_entity: bool = False) -> list[EventCandidate]:
    candidates = []
    for index, body in enumerate(_TEXTS[case]):
        streets = ["Pellegrini", "Oroño" if case == "C" and index == 1 else "Corrientes"]
        if case == "D":
            streets = ["Pellegrini"] if index == 0 else ["Rosario"]
        if include_city_entity:
            streets.append("Rosario")  # Same city is explicit context in scenario C.
        # A/D: 15:00 is a representative afternoon time, not an extracted exact hour.
        hour = (14 if index == 0 else 18) if case == "C" else 15
        candidates.append(EventCandidate(
            event_type="accidente",
            what_happened=body,
            short_summary=body,
            occurred_at=None if case == "B" else datetime(2026, 9, 14, hour, tzinfo=_AR),
            country_code="AR", province="Santa Fe", locality="Rosario",
            address_text=("Pellegrini y Oroño" if index == 1 else "Pellegrini y Corrientes")
            if case == "C" else (None if case == "D" else "Pellegrini y Corrientes"),
            editorial_topic=EditorialTopic.ACCIDENT,
            is_public_affairs=False,
            argentina_relevance=True,
            location_confidence=0.9,
            entities=[ExtractedEntity(name=name, entity_type=EntityType.PLACE, role="lugar") for name in streets],
        ))
    return candidates


def _run_pair(
    session: Session, monkeypatch, record_property, case: str, *, similarity: float,
    isolate_gate: bool = True, include_city_entity: bool = False,
    terra_decision: str = "NEW_EVENT", omit_entities: bool = False,
    candidates: list[EventCandidate] | None = None,
) -> dict:
    candidates = candidates if candidates is not None else _candidates(case, include_city_entity=include_city_entity)
    if omit_entities:
        for candidate in candidates:
            candidate.entities = []
    gate_results = []
    if isolate_gate:
        def allow_dedup(candidate, *, source_text=None):
            result = evaluate_editorial_gate(candidate, source_text=source_text)
            gate_results.append(result.reason)
            return replace(result, allowed=True, reason=None)
        monkeypatch.setattr("app.services.detection_service.evaluate_editorial_gate", allow_dedup)

    items = []
    texts = _TEXTS[case] if case in _TEXTS else [candidate.what_happened for candidate in candidates]
    for index, body in enumerate(texts):
        host = f"source-{index}.test"
        source = SourceService(session).create(SourceCreate(
            name=f"Source {index}", domain=host, feed_url=f"https://{host}/rss",
            preferred_ingestion_method=IngestionMethod.RSS,
        ))
        items.append(SourceItemService(session).ingest(SourceItemCreate(
            source_id=source.id, url=f"https://{host}/{case.lower()}",
            canonical_url=f"https://{host}/{case.lower()}",
            content_hash=f"{case}-{index}", title=body, clean_text=body,
            published_at=datetime(2026, 9, 14, 22, tzinfo=_AR),
        )).item)
    session.commit()
    assert items[0].id != items[1].id and items[0].source_id != items[1].source_id
    assert items[0].url != items[1].url and items[0].clean_text != items[1].clean_text

    # Distinct normalized vectors: cos(v0, v1) = similarity. Zero-pad to the real
    # storage dimension. No input sentinel tokens or forced dedup return values.
    vectors = {
        embedding_text(candidates[0]): [1.0, 0.0] + [0.0] * 1022,
        embedding_text(candidates[1]): [similarity, sqrt(1 - similarity ** 2)] + [0.0] * 1022,
    }
    embedding_calls = []
    embedder = FakeEmbeddingProvider(model="controlled-unit-vectors")
    def embed(texts):
        embedding_calls.append(list(texts))
        return [vectors[value][:] for value in texts]
    monkeypatch.setattr(embedder, "embed", embed)
    extractor = FakeStructuredLLM({"EventCandidate": candidates})
    terra = FakeStructuredLLM()
    service = DetectionService(session, light_llm=extractor, dedup_llm=terra, embeddings=embedder)

    # Observers delegate to the actual repository and dedup methods unchanged.
    retrieval, level1, scores = [], [], []
    real_retrieve = service.events.list_match_candidates
    real_level1 = service._level1_match
    real_score = service._score_embeddings
    def retrieve(**kwargs):
        found = real_retrieve(**kwargs)
        retrieval.append({"filters": kwargs, "ids": [str(event.id) for event in found]})
        return found
    def match(candidate, recent):
        found = real_level1(candidate, recent)
        level1.append(str(found.id) if found else None)
        return found
    def score(candidate, recent):
        found = real_score(candidate, recent)
        scores.append([(str(event.id), value) for event, value in found])
        return found
    monkeypatch.setattr(service.events, "list_match_candidates", retrieve)
    monkeypatch.setattr(service, "_level1_match", match)
    monkeypatch.setattr(service, "_score_embeddings", score)

    first = service.detect(items[0].id)
    session.commit()
    terra.responses["DedupDecision"] = DedupDecision(
        decision=terra_decision,
        event_id=first["event_id"] if terra_decision == "EXISTING_EVENT" else None,
        confidence=0.9,
        reason="Controlled response: same incident" if terra_decision == "EXISTING_EVENT"
        else "Controlled response: insufficient evidence of the same incident",
    )
    second = service.detect(items[1].id)
    session.commit()
    counts = {table: session.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
              for table in ("sources", "source_items", "events", "event_sources")}
    links = [{"source_item_id": str(link.source_item_id), "event_id": str(link.event_id),
              "relation": link.relation_type.value, "is_primary": link.is_primary}
             for link in session.scalars(select(EventSource)).all()]
    report = {
        "case": case, "gate_isolated": isolate_gate, "original_gate_reasons": gate_results,
        "thresholds": {"high": service.settings.event_match_high_threshold,
                       "low": service.settings.event_match_low_threshold,
                       "window_hours": service.settings.event_match_window_hours},
        "input_items": [{"id": str(item.id), "source_id": str(item.source_id),
                         "url": item.url, "body": item.clean_text,
                         "status": item.processing_status.value} for item in items],
        "candidates": [candidate.model_dump(mode="json") for candidate in candidates],
        "retrieval": retrieval, "level1": level1, "scores": scores,
        "controlled_similarity": similarity, "embedding_calls": embedding_calls,
        "terra_calls": terra.calls, "terra_payloads": terra.user_prompts,
        "terra_response": terra.responses["DedupDecision"].model_dump(mode="json"),
        "results": [first, second], "counts": counts, "links": links,
        "events": [{"id": str(event.id), "title": event.title_internal,
                    "summary": event.short_summary, "started_at": event.started_at,
                    "address": event.address_text} for event in session.scalars(select(Event)).all()],
        "runs": [run.metadata_json for run in session.scalars(select(PipelineRun)).all()],
    }
    record_property("dedup_trace", json.dumps(report, ensure_ascii=False, default=str))
    return report


def _assert_outcome(report: dict, *, events: int, reason: str | None = None) -> None:
    assert report["counts"] == {"sources": 2, "source_items": 2, "events": events, "event_sources": 2}
    first, second = report["results"]
    assert first["created"] is True
    assert second["created"] is (events == 2)
    if reason is not None:
        assert second["reason"] == reason
    assert (first["event_id"] == second["event_id"]) is (events == 1)
    assert len({link["event_id"] for link in report["links"]}) == events
    assert {link["source_item_id"] for link in report["links"]} == {item["id"] for item in report["input_items"]}
    assert all(item["status"] == "PROCESSED" for item in report["input_items"])
    assert all(run.get("created") == result["created"] for run, result in zip(report["runs"], report["results"]))


@pytest.mark.parametrize("case", ["A", "B", "C"])
def test_crash_pairs_are_filtered_before_dedup(db_session, monkeypatch, record_property, case):
    report = _run_pair(db_session, monkeypatch, record_property, case, similarity=0.94, isolate_gate=False)
    assert report["counts"] == {"sources": 2, "source_items": 2, "events": 0, "event_sources": 0}
    assert all(result["reason"] == "NOT_PUBLIC_AFFAIRS" for result in report["results"])
    assert report["retrieval"] == report["embedding_calls"] == report["terra_calls"] == []


def test_case_a_distinct_sources_same_incident(db_session, monkeypatch, record_property):
    report = _run_pair(db_session, monkeypatch, record_property, "A", similarity=0.94)
    _assert_outcome(report, events=1)
    assert report["terra_calls"] == []


def test_case_a_without_entities_uses_embedding_high(db_session, monkeypatch, record_property):
    report = _run_pair(db_session, monkeypatch, record_property, "A", similarity=0.94, omit_entities=True)
    _assert_outcome(report, events=1)
    assert report["terra_calls"] == []


def test_case_b_additional_injuries_do_not_create_an_event(db_session, monkeypatch, record_property):
    report = _run_pair(db_session, monkeypatch, record_property, "B", similarity=0.94)
    _assert_outcome(report, events=1)
    assert all(candidate["occurred_at"] is None for candidate in report["candidates"])
    assert report["terra_calls"] == []
    # Linking retains the original event summary; the extra information stays in SourceItem B.
    assert report["events"][0]["summary"] == _TEXTS["B"][0]


@pytest.mark.parametrize("similarity", [0.65, 0.94], ids=["low_similarity", "high_similarity"])
def test_case_c_different_crashes_must_not_merge(db_session, monkeypatch, record_property, similarity):
    report = _run_pair(db_session, monkeypatch, record_property, "C", similarity=similarity)
    assert report["level1"] == [None, None]
    # Acceptance concerns event identity. A future fix may reject a high-score
    # match for contradictions or ask Terra; do not prescribe that implementation.
    _assert_outcome(report, events=2)
    if similarity < report["thresholds"]["low"]:
        assert report["results"][1]["reason"] == f"embedding_low:{similarity:.3f}"
        assert report["terra_calls"] == []


def test_case_c_shared_city_and_avenue_must_not_override_conflicts(db_session, monkeypatch, record_property):
    report = _run_pair(db_session, monkeypatch, record_property, "C", similarity=0.65, include_city_entity=True)
    _assert_outcome(report, events=2)


@pytest.mark.parametrize("decision", ["EXISTING_EVENT", "NEW_EVENT"])
def test_case_d_ambiguous_similarity_uses_terra_decision_and_payload(
    db_session, monkeypatch, record_property, decision,
):
    report = _run_pair(db_session, monkeypatch, record_property, "D", similarity=0.80, terra_decision=decision)
    expected_count = 1 if decision == "EXISTING_EVENT" else 2
    _assert_outcome(report, events=expected_count, reason="terra_existing" if expected_count == 1 else "terra_new")
    assert report["level1"] == [None, None]
    assert report["scores"][1][0][1] == pytest.approx(0.80)
    assert report["thresholds"]["low"] <= 0.80 < report["thresholds"]["high"]
    assert report["terra_calls"] == ["DedupDecision"]
    payload = report["terra_payloads"][0]
    candidate_line, existing_lines = payload.split("\nEventos existentes:\n")
    sent_candidate = json.loads(candidate_line.removeprefix("Candidato: "))
    fields = {"event_type", "what_happened", "occurred_at", "country_code", "province", "locality",
              "neighborhood", "address_text", "entities", "short_summary"}
    assert sent_candidate == {key: report["candidates"][1][key] for key in fields}
    first_event_id = report["results"][0]["event_id"]
    sent_existing = json.loads(existing_lines.removeprefix("- "))
    assert set(sent_existing) == fields | {"id", "score"}
    assert sent_existing["id"] == first_event_id
    assert sent_existing["score"] == pytest.approx(0.80)
    # PostgreSQL returns the stored instant in UTC; compare instants, not spelling.
    assert datetime.fromisoformat(sent_existing["occurred_at"]) == datetime.fromisoformat(report["candidates"][0]["occurred_at"])
    assert {key: sent_existing[key] for key in fields - {"occurred_at"}} == {
        key: report["candidates"][0][key] for key in fields - {"occurred_at"}
    }
    assert report["retrieval"][-1]["ids"] == [first_event_id]


def _political_announcements(*, different: bool = False, different_address: bool = False):
    """No domain rules: shared people/organism are context, not an event ID."""
    texts = (
        "La intendenta Ana Pérez anunció un programa municipal de becas universitarias en Rosario.",
        "Rosario tendrá nuevas becas para estudiantes universitarios: Ana Pérez presentó el programa municipal.",
    )
    if different:
        texts = (texts[0], "La intendenta Ana Pérez anunció un programa municipal de becas para formación laboral en Rosario.")
    if different_address:
        texts = tuple(body + f" El anuncio se realizó en San Martín {100 if index == 0 else 200}."
                      for index, body in enumerate(texts))
    return [EventCandidate(
        event_type="anuncio_oficial", what_happened=body, short_summary=body,
        occurred_at=datetime(2026, 9, 14, 15, tzinfo=_AR),
        country_code="AR", province="Santa Fe", locality="Rosario",
        # Explicit sites of two separate announcements, not project locations.
        address_text=("San Martín 200" if index == 1 else "San Martín 100") if different_address
        else ("San Martín 100" if different else None),
        editorial_topic=EditorialTopic.GOVERNMENT, is_public_affairs=True,
        argentina_relevance=True, location_confidence=0.9,
        entities=[
            ExtractedEntity(name="Ana Pérez", entity_type=EntityType.PERSON, role="anunciante"),
            ExtractedEntity(name="Municipalidad de Rosario", entity_type=EntityType.GOVERNMENT, role="organismo"),
        ],
    ) for index, body in enumerate(texts)]


@pytest.mark.parametrize("similarity", [0.80, 0.94])
def test_political_rewordings_link_the_same_event(db_session, monkeypatch, record_property, similarity):
    report = _run_pair(
        db_session, monkeypatch, record_property, "political_same", similarity=similarity,
        candidates=_political_announcements(), isolate_gate=False, terra_decision="EXISTING_EVENT",
    )
    _assert_outcome(report, events=1)
    assert report["terra_calls"] == (["DedupDecision"] if similarity < report["thresholds"]["high"] else [])


@pytest.mark.parametrize("similarity", [0.80, 0.94])
def test_political_announcements_at_different_addresses_do_not_merge(
    db_session, monkeypatch, record_property, similarity,
):
    report = _run_pair(
        db_session, monkeypatch, record_property, "political_different_addresses", similarity=similarity,
        candidates=_political_announcements(different=True, different_address=True), isolate_gate=False,
        # Even a provider willing to merge cannot restore the excluded Event.
        terra_decision="EXISTING_EVENT",
    )
    _assert_outcome(report, events=2)
    assert report["terra_calls"] == []


def test_shared_political_entities_place_and_time_leave_ambiguous_identity_to_terra(
    db_session, monkeypatch, record_property,
):
    report = _run_pair(
        db_session, monkeypatch, record_property, "political_ambiguous", similarity=0.80,
        candidates=_political_announcements(different=True), isolate_gate=False, terra_decision="NEW_EVENT",
    )
    _assert_outcome(report, events=2)
    assert report["terra_calls"] == ["DedupDecision"]


def test_approximate_times_do_not_exclude_a_political_event_from_terra(
    db_session, monkeypatch, record_property,
):
    candidates = _political_announcements()
    for candidate, hour in zip(candidates, (14, 18), strict=True):
        candidate.occurred_at = datetime(2026, 9, 14, hour, tzinfo=_AR)
        candidate.what_happened += f" La presentación fue alrededor de las {hour}:00."
        candidate.short_summary = candidate.what_happened
    report = _run_pair(
        db_session, monkeypatch, record_property, "political_approximate_times", similarity=0.80,
        candidates=candidates, isolate_gate=False, terra_decision="EXISTING_EVENT",
    )
    _assert_outcome(report, events=1)
    assert report["terra_calls"] == ["DedupDecision"]
    payload = report["terra_payloads"][0]
    candidate_line, existing_lines = payload.split("\nEventos existentes:\n")
    assert datetime.fromisoformat(json.loads(candidate_line.removeprefix("Candidato: "))["occurred_at"]) == candidates[1].occurred_at
    assert datetime.fromisoformat(json.loads(existing_lines.removeprefix("- "))["occurred_at"]) == candidates[0].occurred_at
