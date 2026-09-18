"""Structural contradictions between extracted facts, without interpreting prose.

No conflicts means unknown identity, not proof that two reports are the same
event. The current schema has neither a unique event identifier nor temporal
precision/duration, so those decisions remain with embeddings and, when the
pair is not auto-merged, a structured LLM.

`should_ask_ambiguous_dedup` only marks a below-LOW pair as worth asking.
It never asserts SAME_EVENT. Extracted province/locality are optional signals,
not a gate.
"""

from dataclasses import dataclass
import re

from app.core.text import normalize_name, token_set, usable_text
from app.domain.enums import EntityType
from app.schemas.detection import EventCandidate
from app.services.editorial_gate import LOCALITY_ALIASES, PROVINCE_ALIASES, TARGET_LOCALITY, place_tokens


DEDUP_FIELDS = frozenset({
    "event_type", "what_happened", "occurred_at", "country_code", "province",
    "locality", "neighborhood", "address_text", "entities", "short_summary",
})

_STREET_PREFIX = re.compile(r"^(?:(?:avenida|avda|av|calle|boulevard|bulevar|bv)\.?\s+)+")
_CROSSING = re.compile(r"\s+(?:y|e|esquina(?: de)?|con)\s+|\s*[&/]\s*")
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_NUMERIC_TOKEN = re.compile(r"^\d+(?:[.,]\d+)?$")
_INCIDENT_MARKERS = ("accidente", "choque", "incendio", "colision", "naufragio")
_CRIME_MARKERS = ("homicidio", "asesinato", "robo", "hurto", "feminicidio", "femicidio")
_SOFT_TYPES = frozenset({"", "unknown", "otro"})
_NAMED_ENTITY_TYPES = frozenset({
    EntityType.PERSON,
    EntityType.ORGANIZATION,
    EntityType.COMPANY,
    EntityType.GOVERNMENT,
})
_NEARBY_DATES_SECONDS = 72 * 3600
_PROCESS_FILLER = frozenset({
    "anuncio", "anuncioo", "anunciar", "anunciara", "anunciaran",
    "publico", "publica", "publicar", "publicacion", "publicado", "publicada",
    "establece", "establecio", "indica", "indico", "afirmo", "afirma",
    "declaro", "declara", "sostuvo", "senalo", "senala", "aseguro", "asegura",
    "estimo", "estima", "informo", "informa", "confirmo", "confirma",
    "preciso", "precisa", "calcula", "calculo", "menciono", "menciona",
    "dice", "dijo", "durante", "todavia", "posteriormente", "inicialmente",
    "proximos", "proximo", "mediodia", "manana", "conferencia", "prensa",
    "gobernador", "gobernadora", "ministro", "ministra", "ministerio",
    "funcionario", "funcionaria", "intendente", "intendenta",
    "presidente", "presidenta", "ejecutivo", "legislatura", "congreso",
    "camara", "gobierno", "poder", "casa", "provincia", "provincial",
    "provinciales", "documento", "documentacion", "texto", "oficial",
    "articulado", "proyecto", "ley", "decreto", "medida", "reforma",
    "regimen", "cambio", "modificacion", "envio", "enviado", "enviara",
    "enviaran", "nota", "fuente", "fuentes", "redaccion", "segun",
    "millones", "pesos", "anuales", "anual", "estimado", "estimada",
    "estimaciones", "cifras", "cifra", "porcentaje", "impacto", "costo",
    "verbalmente", "comunicadas", "comunicado", "mencionados", "preliminar",
    "preliminares", "respecto", "ademas", "todavia", "esta", "este",
    "estos", "estas", "parte", "tras", "ante", "hacia", "desde",
    "hecho", "hechos", "caso", "casos", "suceso", "distinto", "distinta",
    "distintos", "distintas", "otro", "otra", "otros", "otras",
    "primer", "primero", "primera", "segundo", "segunda",
    "zona", "norte", "sur", "este", "oeste", "centro", "barrio",
})


@dataclass(frozen=True)
class IdentityComparison:
    conflicts: tuple[str, ...]


def _normalized(value: str | None) -> str:
    return normalize_name(usable_text(value))


def _street(value: str) -> str:
    return _STREET_PREFIX.sub("", value).strip(" .")


def _address(value: str | None) -> tuple[str, ...] | None:
    normalized = _normalized(value)
    parts = [_street(part) for part in _CROSSING.split(normalized)]
    if len(parts) == 2 and all(parts) and parts[0] != parts[1]:
        return ("intersection", *sorted(parts))
    numbered = re.fullmatch(r"(.+?)\s+(?:al\s+)?(\d{1,6})", normalized)
    if numbered and not re.match(r"^(?:ruta|km|kilometro)\b", normalized):
        return ("numbered", _street(numbered[1]), numbered[2])
    return None


def compare_identity(left: EventCandidate, right: EventCandidate) -> IdentityComparison:
    conflicts = []
    for field in ("country_code", "province", "locality"):
        first, second = _normalized(getattr(left, field)), _normalized(getattr(right, field))
        if first and second and first != second:
            conflicts.append(field)

    left_address, right_address = _address(left.address_text), _address(right.address_text)
    if left_address and right_address and left_address[0] == right_address[0] and left_address != right_address:
        conflicts.append("address")

    # occurred_at does not say whether the event is instantaneous, whether the
    # date was explicit/inferred, or how precise its time is. Do not infer any
    # of that from what_happened/summary. These fields remain in Terra's payload.
    return IdentityComparison(conflicts=tuple(conflicts))


def _event_family(event_type: str | None) -> str | None:
    token = _normalized(event_type)
    if token in _SOFT_TYPES:
        return None
    if any(marker in token for marker in _INCIDENT_MARKERS):
        return "incident"
    if any(marker in token for marker in _CRIME_MARKERS):
        return "crime"
    return "civic"


def event_types_compatible(left: EventCandidate, right: EventCandidate) -> bool:
    first, second = _event_family(left.event_type), _event_family(right.event_type)
    if first is None or second is None:
        return True
    return first == second


def _shared_jurisdiction(left: EventCandidate, right: EventCandidate) -> bool:
    for field in ("province", "locality"):
        first, second = _normalized(getattr(left, field)), _normalized(getattr(right, field))
        if first and second and first == second:
            return True
    return False


def _process_years(candidate: EventCandidate) -> set[str]:
    text = _normalized(usable_text(candidate.what_happened, candidate.short_summary))
    return set(_YEAR.findall(text))


def _type_tokens(*candidates: EventCandidate) -> set[str]:
    tokens: set[str] = set()
    for candidate in candidates:
        tokens |= token_set(_normalized(candidate.event_type))
    for marker in _INCIDENT_MARKERS + _CRIME_MARKERS:
        tokens |= token_set(marker)
    return tokens


def _geo_tokens(*candidates: EventCandidate) -> set[str]:
    tokens: set[str] = set()
    aliases = set(LOCALITY_ALIASES)
    aliases.add(TARGET_LOCALITY)
    for alias in PROVINCE_ALIASES:
        aliases |= token_set(alias)
    for candidate in candidates:
        for field in (candidate.country_code, candidate.province, candidate.locality, candidate.neighborhood):
            tokens |= token_set(_normalized(field))
        blob = usable_text(candidate.what_happened, candidate.short_summary)
        for token in place_tokens(blob):
            if token in aliases:
                tokens.add(token)
    return tokens


def _person_tokens(candidate: EventCandidate) -> set[str]:
    tokens: set[str] = set()
    for entity in candidate.entities or []:
        if entity.entity_type == EntityType.PERSON:
            tokens |= token_set(_normalized(entity.name))
    return tokens


def _content_tokens(candidate: EventCandidate, *, drop: set[str]) -> set[str]:
    text = _normalized(usable_text(candidate.what_happened, candidate.short_summary))
    text = _YEAR.sub(" ", text)
    tokens: set[str] = set()
    for token in token_set(text):
        if token in drop or token in _PROCESS_FILLER:
            continue
        if _NUMERIC_TOKEN.match(token) or len(token) < 4:
            continue
        tokens.add(token)
    for entity in candidate.entities or []:
        if entity.entity_type in {EntityType.PERSON, EntityType.PLACE}:
            continue
        for token in token_set(_normalized(entity.name)):
            if token in drop or token in _PROCESS_FILLER or len(token) < 4:
                continue
            if _NUMERIC_TOKEN.match(token):
                continue
            tokens.add(token)
    return tokens


def _token_overlap(left: set[str], right: set[str]) -> set[str]:
    hits = set(left & right)
    used_right = set(hits)
    extra: set[str] = set()
    for first in left:
        if first in hits:
            continue
        for second in right:
            if second in used_right:
                continue
            length = min(len(first), len(second))
            if length >= 5 and first[:5] == second[:5]:
                extra.add(first[:5])
                used_right.add(second)
                break
    return hits | extra


def process_anchors(candidate: EventCandidate, *, other: EventCandidate | None = None) -> set[str]:
    drop = _geo_tokens(candidate, other) if other is not None else _geo_tokens(candidate)
    drop |= _person_tokens(candidate)
    drop |= _type_tokens(candidate, other) if other is not None else _type_tokens(candidate)
    if other is not None:
        drop |= _person_tokens(other)
    return _content_tokens(candidate, drop=drop)


def strong_process_overlap(left: EventCandidate, right: EventCandidate) -> bool:
    return len(process_overlap_tokens(left, right)) >= 2


def process_overlap_tokens(left: EventCandidate, right: EventCandidate) -> tuple[str, ...]:
    overlap = _token_overlap(process_anchors(left, other=right), process_anchors(right, other=left))
    return tuple(sorted(token for token in overlap if len(token) >= 5))


def process_years_conflict(left: EventCandidate, right: EventCandidate) -> bool:
    years_left, years_right = _process_years(left), _process_years(right)
    return bool(years_left and years_right and years_left.isdisjoint(years_right))


def _shared_named_entities(left: EventCandidate, right: EventCandidate) -> bool:
    return bool(_named_entity_keys(left) & _named_entity_keys(right))


def _named_entity_keys(candidate: EventCandidate) -> set[str]:
    keys: set[str] = set()
    for entity in candidate.entities or []:
        if entity.entity_type not in _NAMED_ENTITY_TYPES:
            continue
        normalized = _normalized(entity.name)
        if not normalized:
            continue
        keys.add(normalized)
        for token in token_set(normalized):
            if len(token) >= 4:
                keys.add(token)
    return keys


def coincidence_signals(left: EventCandidate, right: EventCandidate) -> tuple[str, ...]:
    """Descriptive overlap for the LLM payload. Not proof of identity."""
    found: list[str] = []
    if event_types_compatible(left, right):
        found.append("compatible_type")
    if _shared_jurisdiction(left, right):
        found.append("shared_location")
    if _shared_named_entities(left, right):
        found.append("shared_entities")
    if process_overlap_tokens(left, right):
        found.append("shared_process")
    if _nearby_dates(left, right):
        found.append("nearby_dates")
    return tuple(found)


def _nearby_dates(left: EventCandidate, right: EventCandidate) -> bool:
    start, end = left.occurred_at, right.occurred_at
    if start is None or end is None:
        return False
    return abs((start - end).total_seconds()) <= _NEARBY_DATES_SECONDS


def should_ask_ambiguous_dedup(left: EventCandidate, right: EventCandidate) -> bool:
    """Below-LOW pair with coincidence signals. Never an automatic merge."""
    if compare_identity(left, right).conflicts:
        return False
    if not event_types_compatible(left, right):
        return False
    if process_years_conflict(left, right):
        return False
    if strong_process_overlap(left, right):
        return True
    return _shared_named_entities(left, right)


def is_structural_terra_candidate(left: EventCandidate, right: EventCandidate) -> bool:
    """Alias histórico: misma puerta, sin exigir provincia/localidad extraídas."""
    return should_ask_ambiguous_dedup(left, right)
