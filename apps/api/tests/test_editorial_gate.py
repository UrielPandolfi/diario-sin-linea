from datetime import datetime, timezone

from app.schemas.detection import EditorialScope, EventCandidate
from app.services.editorial_gate import (
    EditorialFilterReason,
    evaluate_editorial_gate,
    needs_location_fallback,
)


def _candidate(**overrides) -> EventCandidate:
    payload = {
        "event_type": "accidente",
        "what_happened": "Un colectivo chocó en Pellegrini y Corrientes",
        "occurred_at": datetime(2026, 8, 23, 15, 0, tzinfo=timezone.utc),
        "locality": "Rosario",
        "province": "Santa Fe",
        "country_code": "AR",
        "short_summary": "Choque de un colectivo en Rosario",
        "editorial_scope": EditorialScope.GENERAL_NEWS,
        "location_confidence": 0.9,
        "entities": [],
    }
    payload.update(overrides)
    return EventCandidate(**payload)


def test_gate_allows_rosario_accident() -> None:
    result = evaluate_editorial_gate(_candidate())
    assert result.allowed is True
    assert result.reason is None


def test_gate_allows_locality_with_province_in_field() -> None:
    result = evaluate_editorial_gate(
        _candidate(locality="Rosario, Santa Fe", province=None)
    )
    assert result.allowed is True


def test_gate_allows_sports_public_impact_in_rosario() -> None:
    result = evaluate_editorial_gate(
        _candidate(
            event_type="disturbios",
            what_happened="Disturbios con heridos en el Gigante de Arroyito",
            short_summary="Incidentes con heridos en Rosario",
            editorial_scope=EditorialScope.SPORTS_PUBLIC_IMPACT,
            editorial_reason="violencia en estadio con heridos",
        )
    )
    assert result.allowed is True


def test_gate_skips_colapinto_sports_only() -> None:
    result = evaluate_editorial_gate(
        _candidate(
            event_type="otro",
            what_happened="Colapinto terminó 12° en Monza",
            locality="Monza",
            province=None,
            country_code="IT",
            short_summary="Resultado de F1",
            editorial_scope=EditorialScope.SPORTS_ONLY,
            editorial_reason="resultado de carrera",
        )
    )
    assert result.allowed is False
    assert result.reason == EditorialFilterReason.SPORTS_ONLY


def test_gate_skips_newells_match() -> None:
    result = evaluate_editorial_gate(
        _candidate(
            event_type="otro",
            what_happened="Newell's ganó 2-1 en el Coloso",
            short_summary="Resultado de fútbol",
            editorial_scope=EditorialScope.SPORTS_ONLY,
        )
    )
    assert result.allowed is False
    assert result.reason == EditorialFilterReason.SPORTS_ONLY


def test_gate_skips_irrelevant() -> None:
    result = evaluate_editorial_gate(
        _candidate(
            editorial_scope=EditorialScope.IRRELEVANT,
            what_happened="Promoción de supermercado",
            short_summary="Publicidad",
        )
    )
    assert result.allowed is False
    assert result.reason == EditorialFilterReason.IRRELEVANT


def test_gate_skips_cordoba() -> None:
    result = evaluate_editorial_gate(
        _candidate(locality="Córdoba", province="Córdoba")
    )
    assert result.allowed is False
    assert result.reason == EditorialFilterReason.OUTSIDE_TARGET_LOCALITY


def test_gate_skips_missing_locality() -> None:
    result = evaluate_editorial_gate(_candidate(locality=None, province="Santa Fe"))
    assert result.allowed is False
    assert result.reason == EditorialFilterReason.LOCATION_UNKNOWN


def test_gate_skips_rosario_with_other_province() -> None:
    result = evaluate_editorial_gate(_candidate(locality="Rosario", province="Córdoba"))
    assert result.allowed is False
    assert result.reason == EditorialFilterReason.OUTSIDE_TARGET_LOCALITY


def test_location_fallback_when_low_confidence_and_empty() -> None:
    assert needs_location_fallback(_candidate(locality=None, location_confidence=0.2)) is True
    assert needs_location_fallback(_candidate(location_confidence=0.9)) is False
    assert needs_location_fallback(_candidate(locality=None, location_confidence=0.9)) is False
