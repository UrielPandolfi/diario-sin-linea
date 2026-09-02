from datetime import datetime, timezone

from app.schemas.detection import EditorialScope, EditorialTopic, EventCandidate, RelevanceLevel
from app.services.editorial_gate import (
    EditorialFilterReason,
    evaluate_editorial_gate,
    needs_location_fallback,
)


def _candidate(**overrides) -> EventCandidate:
    payload = {
        "event_type": "anuncio_oficial",
        "what_happened": "El Gobierno dispuso un aumento salarial para las Fuerzas Armadas",
        "occurred_at": datetime(2026, 8, 23, 15, 0, tzinfo=timezone.utc),
        "locality": "Buenos Aires",
        "province": "Buenos Aires",
        "country_code": "AR",
        "short_summary": "Aumento salarial para las Fuerzas Armadas",
        "editorial_scope": EditorialScope.GENERAL_NEWS,
        "editorial_topic": EditorialTopic.GOVERNMENT,
        "is_public_affairs": True,
        "political_relevance": RelevanceLevel.HIGH,
        "location_confidence": 0.9,
        "entities": [],
    }
    payload.update(overrides)
    return EventCandidate(**payload)


def _crash(**overrides) -> EventCandidate:
    payload = {
        "event_type": "accidente",
        "what_happened": "Un colectivo chocó en Pellegrini y Corrientes",
        "locality": "Rosario",
        "province": "Santa Fe",
        "country_code": "AR",
        "short_summary": "Choque de un colectivo en Rosario",
        "editorial_scope": EditorialScope.GENERAL_NEWS,
        "editorial_topic": EditorialTopic.ACCIDENT,
        "is_public_affairs": False,
        "political_relevance": RelevanceLevel.NONE,
        "public_interest_relevance": RelevanceLevel.MEDIUM,
        "location_confidence": 0.9,
        "entities": [],
    }
    payload.update(overrides)
    return _candidate(**payload)


def test_gate_allows_national_politics_in_buenos_aires() -> None:
    result = evaluate_editorial_gate(_candidate())
    assert result.allowed is True
    assert result.reason is None


def test_gate_allows_provincial_politics_in_cordoba() -> None:
    result = evaluate_editorial_gate(
        _candidate(
            locality="Córdoba",
            province="Córdoba",
            editorial_topic=EditorialTopic.PROVINCIAL_POLITICS,
            what_happened="La gobernación de Córdoba anunció un recorte presupuestario",
            short_summary="Recorte presupuestario provincial",
        )
    )
    assert result.allowed is True


def test_gate_allows_national_economy_policy() -> None:
    result = evaluate_editorial_gate(
        _candidate(
            editorial_topic=EditorialTopic.PUBLIC_ECONOMY,
            what_happened="El Ministerio de Economía modificó alícuotas de impuestos",
            short_summary="Cambio de impuestos",
        )
    )
    assert result.allowed is True


def test_gate_allows_electoral_poll() -> None:
    result = evaluate_editorial_gate(
        _candidate(
            editorial_topic=EditorialTopic.ELECTIONS,
            is_public_affairs=False,
            political_relevance=RelevanceLevel.NONE,
            what_happened="Una encuesta ubica al oficialismo por encima de la oposición",
            short_summary="Encuesta electoral",
        )
    )
    assert result.allowed is True


def test_gate_allows_presidential_decree() -> None:
    result = evaluate_editorial_gate(
        _candidate(
            locality=None,
            province=None,
            editorial_topic=EditorialTopic.LEGISLATION,
            what_happened="El Presidente firmó un decreto de necesidad y urgencia",
            short_summary="Decreto presidencial",
        )
    )
    assert result.allowed is True


def test_gate_allows_congress_bill() -> None:
    result = evaluate_editorial_gate(
        _candidate(
            editorial_topic=EditorialTopic.LEGISLATION,
            what_happened="Diputados debate un proyecto de ley de presupuesto",
            short_summary="Proyecto del Congreso",
        )
    )
    assert result.allowed is True


def test_gate_allows_judicial_case_against_official() -> None:
    result = evaluate_editorial_gate(
        _candidate(
            editorial_topic=EditorialTopic.JUSTICE,
            what_happened="Investigan al ministro de Seguridad por una contratación irregular",
            short_summary="Causa contra un funcionario",
        )
    )
    assert result.allowed is True


def test_gate_allows_energy_policy() -> None:
    result = evaluate_editorial_gate(
        _candidate(
            editorial_topic=EditorialTopic.PUBLIC_ECONOMY,
            what_happened="El Gobierno modificó la política de tarifas energéticas",
            short_summary="Política energética",
        )
    )
    assert result.allowed is True


def test_gate_allows_armed_forces_decision() -> None:
    result = evaluate_editorial_gate(
        _candidate(
            what_happened="El Gobierno dispuso un aumento adicional del 12,22% para las Fuerzas Armadas",
            short_summary="Aumento a las Fuerzas Armadas",
        )
    )
    assert result.allowed is True


def test_gate_allows_rosario_politics() -> None:
    result = evaluate_editorial_gate(
        _candidate(
            locality="Rosario",
            province="Santa Fe",
            editorial_topic=EditorialTopic.PROVINCIAL_POLITICS,
            what_happened="El Concejo Municipal de Rosario aprobó una ordenanza fiscal",
            short_summary="Ordenanza fiscal en Rosario",
        )
    )
    assert result.allowed is True


def test_gate_skips_crash_in_rosario() -> None:
    result = evaluate_editorial_gate(_crash())
    assert result.allowed is False
    assert result.reason == EditorialFilterReason.NOT_PUBLIC_AFFAIRS


def test_gate_skips_crash_in_cordoba() -> None:
    result = evaluate_editorial_gate(_crash(locality="Córdoba", province="Córdoba"))
    assert result.allowed is False
    assert result.reason == EditorialFilterReason.NOT_PUBLIC_AFFAIRS


def test_gate_skips_common_robbery() -> None:
    result = evaluate_editorial_gate(
        _crash(
            event_type="robo",
            editorial_topic=EditorialTopic.CRIME,
            what_happened="Dos personas robaron un comercio",
            short_summary="Robo a un comercio",
        )
    )
    assert result.allowed is False
    assert result.reason == EditorialFilterReason.NOT_PUBLIC_AFFAIRS


def test_gate_skips_common_fire() -> None:
    result = evaluate_editorial_gate(
        _crash(
            event_type="incendio",
            editorial_topic=EditorialTopic.OTHER,
            what_happened="Ardió un depósito en zona norte",
            short_summary="Incendio cotidiano",
        )
    )
    assert result.allowed is False


def test_gate_skips_football() -> None:
    result = evaluate_editorial_gate(
        _candidate(
            editorial_scope=EditorialScope.SPORTS_ONLY,
            editorial_topic=EditorialTopic.SPORTS,
            is_public_affairs=False,
            political_relevance=RelevanceLevel.NONE,
            what_happened="Newell's ganó 2-1 en el Coloso",
            short_summary="Resultado de fútbol",
        )
    )
    assert result.allowed is False
    assert result.reason == EditorialFilterReason.SPORTS_ONLY


def test_gate_skips_entertainment() -> None:
    result = evaluate_editorial_gate(
        _candidate(
            editorial_scope=EditorialScope.IRRELEVANT,
            editorial_topic=EditorialTopic.ENTERTAINMENT,
            is_public_affairs=False,
            political_relevance=RelevanceLevel.NONE,
            what_happened="Una celebridad estrenó una serie",
            short_summary="Estreno de entretenimiento",
        )
    )
    assert result.allowed is False
    assert result.reason == EditorialFilterReason.IRRELEVANT


def test_gate_justice_topic_alone_does_not_pass() -> None:
    result = evaluate_editorial_gate(
        _candidate(
            editorial_topic=EditorialTopic.JUSTICE,
            is_public_affairs=False,
            political_relevance=RelevanceLevel.NONE,
            what_happened="Un tribunal condenó a un particular por un hurto",
            short_summary="Condena por hurto",
        )
    )
    assert result.allowed is False
    assert result.reason == EditorialFilterReason.NOT_PUBLIC_AFFAIRS


def test_gate_public_health_topic_alone_does_not_pass() -> None:
    result = evaluate_editorial_gate(
        _candidate(
            editorial_topic=EditorialTopic.PUBLIC_HEALTH,
            is_public_affairs=False,
            political_relevance=RelevanceLevel.NONE,
            what_happened="Un hospital atendió un pico de consultas por gripe",
            short_summary="Consultas por gripe",
        )
    )
    assert result.allowed is False


def test_gate_public_security_topic_alone_does_not_pass() -> None:
    result = evaluate_editorial_gate(
        _candidate(
            editorial_topic=EditorialTopic.PUBLIC_SECURITY,
            is_public_affairs=False,
            political_relevance=RelevanceLevel.NONE,
            what_happened="La policía detuvo a dos personas por un robo",
            short_summary="Detención policial",
        )
    )
    assert result.allowed is False
    assert result.reason == EditorialFilterReason.NOT_PUBLIC_AFFAIRS


def test_gate_public_education_topic_alone_does_not_pass() -> None:
    result = evaluate_editorial_gate(
        _candidate(
            editorial_topic=EditorialTopic.PUBLIC_EDUCATION,
            is_public_affairs=False,
            political_relevance=RelevanceLevel.NONE,
            what_happened="Una escuela reprogramó clases por un acto",
            short_summary="Cambio de horario escolar",
        )
    )
    assert result.allowed is False


def test_gate_public_economy_topic_alone_does_not_pass() -> None:
    result = evaluate_editorial_gate(
        _candidate(
            editorial_topic=EditorialTopic.PUBLIC_ECONOMY,
            is_public_affairs=False,
            political_relevance=RelevanceLevel.NONE,
            what_happened="Subió el precio de un recorte de carne en un supermercado",
            short_summary="Precio de un producto",
        )
    )
    assert result.allowed is False


def test_gate_legislation_topic_is_strong_signal() -> None:
    result = evaluate_editorial_gate(
        _candidate(
            editorial_topic=EditorialTopic.LEGISLATION,
            is_public_affairs=False,
            political_relevance=RelevanceLevel.NONE,
            what_happened="El Senado trató un proyecto de reforma",
            short_summary="Proyecto de reforma",
        )
    )
    assert result.allowed is True


def test_gate_skips_foreign_politics_without_argentina_relevance() -> None:
    result = evaluate_editorial_gate(
        _candidate(
            country_code="FR",
            locality="París",
            province=None,
            argentina_relevance=False,
            what_happened="La Asamblea Nacional francesa aprobó un presupuesto",
            short_summary="Presupuesto francés",
        )
    )
    assert result.allowed is False
    assert result.reason == EditorialFilterReason.OUTSIDE_TARGET_COUNTRY


def test_gate_allows_foreign_news_with_argentina_relevance() -> None:
    result = evaluate_editorial_gate(
        _candidate(
            country_code="US",
            locality="Washington",
            province=None,
            argentina_relevance=True,
            editorial_topic=EditorialTopic.INTERNATIONAL_AR,
            what_happened="Estados Unidos anunció aranceles que afectan exportaciones argentinas",
            short_summary="Aranceles con impacto argentino",
        )
    )
    assert result.allowed is True


def test_gate_allows_locality_with_province_in_field() -> None:
    candidate = _candidate(locality="Rosario, Santa Fe", province=None)
    result = evaluate_editorial_gate(candidate)
    assert result.allowed is True
    assert candidate.locality == "Rosario"
    assert candidate.province == "Santa Fe"


def test_canonicalize_does_not_rewrite_cordoba_as_rosario() -> None:
    from app.services.editorial_gate import apply_canonical_location

    candidate = apply_canonical_location(
        _candidate(locality="Córdoba", province="Córdoba")
    )
    assert candidate.locality == "Córdoba"
    assert candidate.province == "Córdoba"


def test_gate_skips_colapinto_sports_only() -> None:
    result = evaluate_editorial_gate(
        _candidate(
            event_type="otro",
            what_happened="Colapinto terminó 12° en Monza",
            locality="Monza",
            province=None,
            country_code="IT",
            argentina_relevance=False,
            short_summary="Resultado de F1",
            editorial_scope=EditorialScope.SPORTS_ONLY,
            editorial_topic=EditorialTopic.SPORTS,
            is_public_affairs=False,
            political_relevance=RelevanceLevel.NONE,
            editorial_reason="resultado de carrera",
        )
    )
    assert result.allowed is False
    assert result.reason == EditorialFilterReason.SPORTS_ONLY


def test_gate_skips_stadium_disturbances_without_public_affairs() -> None:
    result = evaluate_editorial_gate(
        _candidate(
            event_type="disturbios",
            what_happened="Disturbios con heridos en el Gigante de Arroyito",
            locality="Rosario",
            province="Santa Fe",
            short_summary="Incidentes con heridos en Rosario",
            editorial_scope=EditorialScope.SPORTS_PUBLIC_IMPACT,
            editorial_topic=EditorialTopic.CRIME,
            is_public_affairs=False,
            political_relevance=RelevanceLevel.NONE,
            editorial_reason="violencia en estadio con heridos",
        )
    )
    assert result.allowed is False
    assert result.reason == EditorialFilterReason.SPORTS_ONLY


def test_gate_skips_formative_leagues_even_if_llm_says_general_news() -> None:
    result = evaluate_editorial_gate(
        _candidate(
            event_type="protesta",
            what_happened=(
                "Rosario será sede de varios torneos de ligas formativas y Copa Santa Fe "
                "entre Náutico y Gimnasia, con fechas y sedes definidas para U15, U17 y femeninas U13."
            ),
            locality="Rosario",
            province="Santa Fe",
            short_summary="Torneos de ligas formativas en Rosario",
            editorial_scope=EditorialScope.GENERAL_NEWS,
            editorial_topic=EditorialTopic.SPORTS,
            is_public_affairs=False,
            political_relevance=RelevanceLevel.NONE,
        )
    )
    assert result.allowed is False
    assert result.reason == EditorialFilterReason.SPORTS_ONLY


def test_location_fallback_skips_missing_city_in_argentina() -> None:
    assert needs_location_fallback(_candidate(locality=None, location_confidence=0.2)) is False
    assert needs_location_fallback(_candidate(location_confidence=0.9)) is False


def test_location_fallback_when_contradictory_and_low_confidence() -> None:
    assert (
        needs_location_fallback(
            _candidate(locality="Rosario", province="Córdoba", location_confidence=0.2)
        )
        is True
    )
