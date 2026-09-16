"""Structural contradictions between extracted facts, without interpreting prose.

No conflicts means unknown identity, not proof that two reports are the same
event. The current schema has neither a unique event identifier nor temporal
precision/duration, so those decisions remain with embeddings/Terra.
"""

from dataclasses import dataclass
import re

from app.core.text import normalize_name, usable_text
from app.schemas.detection import EventCandidate


DEDUP_FIELDS = frozenset({
    "event_type", "what_happened", "occurred_at", "country_code", "province",
    "locality", "neighborhood", "address_text", "entities", "short_summary",
})

_STREET_PREFIX = re.compile(r"^(?:(?:avenida|avda|av|calle|boulevard|bulevar|bv)\.?\s+)+")
_CROSSING = re.compile(r"\s+(?:y|e|esquina(?: de)?|con)\s+|\s*[&/]\s*")


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
