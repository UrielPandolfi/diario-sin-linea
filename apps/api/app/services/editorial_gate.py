"""Filtro editorial determinista: deportes-only / irrelevante / fuera de Rosario.

Puede correr sobre el texto crudo (prefiltro, sin LLM) y otra vez sobre el
EventCandidate. No llama LLM. Normaliza país/provincia/localidad.
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
LOCALITY_DISPLAY = {"rosario": "Rosario"}
PROVINCE_DISPLAY = {"santa fe": "Santa Fe", "santafe": "Santa Fe"}

# Fallback a Luna si la confianza es menor y no hay localidad usable o hay contradicción.
LOCATION_CONFIDENCE_FALLBACK = 0.4

_SPLIT = re.compile(r"[\s,;|/–—\-]+")

# Cobertura deportiva (texto ya plegado, sin acentos). Un match fuerte alcanza.
_SPORTS_STRONG = re.compile(
    r"\b(?:"
    r"ligas? formativas?|liga federal formativa|"
    r"basquet(?:bol)?|basketball|futbol(?:istas?)?|rugby|hockey|"
    r"voley(?:bol)?|tenis|padel|formula ?1|\bf1\b|colapinto|"
    r"fixture|goleador(?:es)?|tabla de posiciones|"
    r"copa santa fe|newell'?s|rosario central|"
    r"u-?1[3579]|u-?2[013]|sub[-\s]?1[3579]|sub[-\s]?2[013]|"
    r"cronica deportiva|hinchada|"
    r"gano \d+\s*[-–]\s*\d+|perdio \d+\s*[-–]\s*\d+"
    r")\b"
)
_SPORTS_WEAK = re.compile(
    r"\b(?:"
    r"torneos?|copa|campeonato|partidos?|clubes|"
    r"nautico|gimnasia|son locales|visitante|"
    r"fecha \d+"
    r")\b"
)
_PUBLIC_NEWS_IMPACT = re.compile(
    r"\b(?:"
    r"herid[oa]s?|muert[oa]s?|victimas?|homicidio|asesinat|"
    r"balacera|tiroteo|apunal|crimen|incendio|explosi|"
    r"accidente|choque|colision|detencion|detenid|"
    r"allanamiento|corrupcion|disturbios?|violencia|"
    r"lincham|denuncia penal|derrumbe|desplome|balazo"
    r")\b"
)


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


def join_editorial_text(*parts: str | None) -> str:
    return " ".join(part.strip() for part in parts if part and str(part).strip())


def item_editorial_text(item: object) -> str:
    return join_editorial_text(
        getattr(item, "title", None),
        getattr(item, "excerpt", None),
        getattr(item, "clean_text", None),
    )


def looks_like_sports_coverage(text: str) -> bool:
    folded = fold_place(text)
    if not folded:
        return False
    if _SPORTS_STRONG.search(folded):
        return True
    return len(set(_SPORTS_WEAK.findall(folded))) >= 2


def has_public_news_impact(text: str) -> bool:
    folded = fold_place(text)
    return bool(folded and _PUBLIC_NEWS_IMPACT.search(folded))


def should_filter_sports(text: str) -> bool:
    """True si el texto es cobertura deportiva sin hecho de interés público."""
    return looks_like_sports_coverage(text) and not has_public_news_impact(text)


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


def split_locality_raw(locality: str | None) -> tuple[str | None, str | None]:
    """Separa ciudad y provincia si vinieron juntas. Conserva el texto original."""
    if not locality or not locality.strip():
        return None, None
    if "," in locality or ";" in locality:
        parts = [part.strip() for part in re.split(r"[,;]", locality) if part.strip()]
        if len(parts) >= 2:
            return parts[0], parts[1]
        if parts:
            return parts[0], None
        return None, None
    return locality.strip(), None


def parse_locality_field(locality: str | None) -> tuple[str | None, str | None]:
    """Acepta `rosario, santa fe` → (rosario, santa fe) folded."""
    loc_raw, prov_raw = split_locality_raw(locality)
    loc = fold_place(loc_raw) or None
    prov = fold_place(prov_raw) or None
    return loc, prov


def _display_place(value: str | None, *, mapping: dict[str, str]) -> str | None:
    if not value or not value.strip():
        return None
    folded = fold_place(value)
    if folded in mapping:
        return mapping[folded]
    compact = folded.replace(" ", "")
    if compact in mapping:
        return mapping[compact]
    return value.strip()


def canonicalize_location(
    candidate: EventCandidate,
) -> tuple[str | None, str | None, str | None]:
    """Ciudad y provincia en campos separados, con display canónico (Rosario / Santa Fe)."""
    loc_raw, loc_province_raw = split_locality_raw(candidate.locality)
    locality = _display_place(loc_raw, mapping=LOCALITY_DISPLAY)
    province = _display_place(candidate.province, mapping=PROVINCE_DISPLAY) or _display_place(
        loc_province_raw, mapping=PROVINCE_DISPLAY
    )
    country = normalize_country(candidate.country_code)
    return locality, province, country


def apply_canonical_location(candidate: EventCandidate) -> EventCandidate:
    locality, province, country = canonicalize_location(candidate)
    candidate.locality = locality
    candidate.province = province
    if country:
        candidate.country_code = country
    return candidate


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


def evaluate_editorial_gate(
    candidate: EventCandidate,
    *,
    source_text: str | None = None,
) -> EditorialGateResult:
    apply_canonical_location(candidate)
    scope = candidate.editorial_scope or EditorialScope.GENERAL_NEWS
    loc = fold_place(candidate.locality)
    province = fold_place(candidate.province)
    country = candidate.country_code
    blob = join_editorial_text(
        candidate.what_happened,
        candidate.short_summary,
        candidate.editorial_reason,
        source_text,
    )
    sports = looks_like_sports_coverage(blob)
    impact = has_public_news_impact(blob)

    def _result(allowed: bool, reason: str | None) -> EditorialGateResult:
        return EditorialGateResult(
            allowed=allowed,
            reason=reason,
            country_code=country,
            province=candidate.province,
            locality=candidate.locality,
            editorial_scope=scope,
        )

    if scope == EditorialScope.IRRELEVANT:
        return _result(False, EditorialFilterReason.IRRELEVANT)
    if scope == EditorialScope.SPORTS_ONLY and not impact:
        return _result(False, EditorialFilterReason.SPORTS_ONLY)
    if sports and not impact:
        return _result(False, EditorialFilterReason.SPORTS_ONLY)
    if scope == EditorialScope.SPORTS_PUBLIC_IMPACT and not impact:
        return _result(False, EditorialFilterReason.SPORTS_ONLY)

    if not loc:
        return _result(False, EditorialFilterReason.LOCATION_UNKNOWN)

    if country and country != TARGET_COUNTRY:
        return _result(False, EditorialFilterReason.OUTSIDE_TARGET_LOCALITY)

    if not locality_is_rosario(loc):
        return _result(False, EditorialFilterReason.OUTSIDE_TARGET_LOCALITY)

    if province and not province_is_santa_fe(province):
        return _result(False, EditorialFilterReason.OUTSIDE_TARGET_LOCALITY)

    return _result(True, None)
