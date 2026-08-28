"""Filtro editorial determinista: deportes-only / irrelevante / fuera de Rosario.

Se evalúa después de extraer EventCandidate y antes de embeddings, dedup o create Event.
No llama LLM. Normaliza país/provincia/localidad (trim, acentos, 'rosario, santa fe').
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.text import normalize_name
from app.schemas.detection import EditorialScope, EventCandidate

TARGET_COUNTRY = "AR"
TARGET_LOCALITY = "rosario"

COUNTRY_AR_ALIASES = {"ar", "arg", "argentina"}
PROVINCE_ALIASES = {"santa fe", "santafe"}
LOCALITY_ALIASES = {"rosario"}

# Fallback a Luna si la confianza es menor y no hay localidad usable o hay contradicción.
LOCATION_CONFIDENCE_FALLBACK = 0.4

_SPLIT = re.compile(r"[\s,;|/–—\-]+")


class EditorialFilterReason:
    SPORTS_ONLY = "SPORTS_ONLY"
    IRRELEVANT = "IRRELEVANT"
    LOCATION_UNKNOWN = "LOCATION_UNKNOWN"
    OUTSIDE_TARGET_LOCALITY = "OUTSIDE_TARGET_LOCALITY"


@dataclass(frozen=True)
class EditorialGateResult:
    allowed: bool
    reason: str | None
    country_code: str | None
    province: str | None
    locality: str | None
    editorial_scope: EditorialScope


def fold_place(value: str | None) -> str:
    if not value:
        return ""
    return normalize_name(value.strip())


def place_tokens(value: str | None) -> list[str]:
    folded = fold_place(value)
    if not folded:
        return []
    return [token for token in _SPLIT.split(folded) if token]


def normalize_country(value: str | None) -> str | None:
    folded = fold_place(value)
    if not folded:
        return None
    if folded in COUNTRY_AR_ALIASES:
        return TARGET_COUNTRY
    if len(folded) == 2:
        return folded.upper()
    return folded.upper()[:8]


def parse_locality_field(locality: str | None) -> tuple[str | None, str | None]:
    """Acepta `rosario, santa fe` → (rosario, santa fe)."""
    if not locality or not locality.strip():
        return None, None
    if "," in locality or ";" in locality:
        parts = [fold_place(part) for part in re.split(r"[,;]", locality) if fold_place(part)]
        if len(parts) >= 2:
            return parts[0], parts[1]
        if parts:
            return parts[0], None
        return None, None
    folded = fold_place(locality)
    return (folded or None), None


def locality_is_rosario(locality: str | None) -> bool:
    folded = fold_place(locality)
    if not folded:
        return False
    if folded in LOCALITY_ALIASES:
        return True
    return TARGET_LOCALITY in place_tokens(locality)


def province_is_santa_fe(province: str | None) -> bool:
    folded = fold_place(province)
    if not folded:
        return False
    return folded in PROVINCE_ALIASES or folded.replace(" ", "") == "santafe"


def location_is_contradictory(candidate: EventCandidate) -> bool:
    """Rosario con provincia que no es Santa Fe (p.ej. Córdoba)."""
    loc, loc_province = parse_locality_field(candidate.locality)
    province = fold_place(candidate.province) or loc_province
    if locality_is_rosario(loc) and province and not province_is_santa_fe(province):
        return True
    return False


def needs_location_fallback(
    candidate: EventCandidate,
    *,
    threshold: float = LOCATION_CONFIDENCE_FALLBACK,
) -> bool:
    """True si conviene reextraer con Luna: poca confianza y localidad vacía o contradictoria."""
    if candidate.location_confidence >= threshold:
        return False
    loc, _ = parse_locality_field(candidate.locality)
    if not loc:
        return True
    return location_is_contradictory(candidate)


def evaluate_editorial_gate(candidate: EventCandidate) -> EditorialGateResult:
    scope = candidate.editorial_scope or EditorialScope.GENERAL_NEWS
    loc, loc_province = parse_locality_field(candidate.locality)
    province = fold_place(candidate.province) or loc_province
    country = normalize_country(candidate.country_code)

    def _result(allowed: bool, reason: str | None) -> EditorialGateResult:
        return EditorialGateResult(
            allowed=allowed,
            reason=reason,
            country_code=country,
            province=candidate.province,
            locality=candidate.locality,
            editorial_scope=scope,
        )

    if scope == EditorialScope.SPORTS_ONLY:
        return _result(False, EditorialFilterReason.SPORTS_ONLY)
    if scope == EditorialScope.IRRELEVANT:
        return _result(False, EditorialFilterReason.IRRELEVANT)

    if not loc:
        return _result(False, EditorialFilterReason.LOCATION_UNKNOWN)

    if country and country != TARGET_COUNTRY:
        return _result(False, EditorialFilterReason.OUTSIDE_TARGET_LOCALITY)

    if not locality_is_rosario(loc):
        return _result(False, EditorialFilterReason.OUTSIDE_TARGET_LOCALITY)

    if province and not province_is_santa_fe(province):
        return _result(False, EditorialFilterReason.OUTSIDE_TARGET_LOCALITY)

    return _result(True, None)
