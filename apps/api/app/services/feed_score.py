"""Principal and Últimas scores.

Principal, with a selected locality that resolves to one place:

    base = 0.45 * relevance + 0.35 * freshness + 0.20 * proximity
    principal = base + 0.15 * confidence * affinity

Without a selected locality the proximity term is dropped and the other two
weights are renormalized. These coefficients are the initial product values
in Settings; they are not calibrated against real reading.

Dates are UTC. Freshness uses the last published material update when that
timestamp exists, otherwise the first public publication. It does not use
technical updated_at. Latest order uses only the first public publication.

Themes come from Event.event_type. editorial_topic is not stored on the
event, so it is not a feed signal. Blank, unknown and "otro" do not contribute
affinity. A missing relevance_score is 0.5; a stored 0 stays 0.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.services.editorial_gate import fold_place

_UNUSED_TOPICS = frozenset({"", "unknown", "otro", "other", "none", "null"})


@dataclass(frozen=True)
class PrincipalWeights:
    relevance: float = 0.45
    freshness: float = 0.35
    locality: float = 0.20
    affinity_boost: float = 0.15
    confidence_events: int = 5
    read_weight: float = 1.0
    like_weight: float = 3.0
    freshness_halflife_hours: float = 24.0
    missing_relevance: float = 0.5


@dataclass(frozen=True)
class Place:
    country: str
    province: str
    locality: str


@dataclass(frozen=True)
class AffinityProfile:
    topic_weights: dict[str, float]
    confidence: float


def empty_profile() -> AffinityProfile:
    return AffinityProfile({}, 0.0)


def topic_key(event_type: str | None) -> str | None:
    key = (event_type or "").casefold().strip()
    if key in _UNUSED_TOPICS:
        return None
    return key


def relevance_unit(score: int | None, *, missing: float) -> float:
    if score is None:
        return missing
    return max(0.0, min(1.0, float(score) / 100.0))


def freshness_unit(reference: datetime | None, now: datetime, *, halflife_hours: float) -> float:
    if reference is None or halflife_hours <= 0:
        return 0.0
    age_hours = max(0.0, (now - reference).total_seconds() / 3600.0)
    return 2.0 ** (-age_hours / halflife_hours)


def principal_reference(material_update_at: datetime | None, published_at: datetime | None) -> datetime | None:
    return material_update_at or published_at


def resolve_place(events: list[tuple[str | None, str | None, str | None]], selected: str | None) -> Place | None:
    """Match a chosen locality only when public rows share one country and province.

    A homonym in another province does not count. An unknown name does not match.
    """
    wanted = fold_place(selected)
    if not wanted:
        return None
    countries: set[str] = set()
    provinces: set[str] = set()
    for country_code, province, locality in events:
        if fold_place(locality) != wanted or not fold_place(province):
            continue
        countries.add(fold_place(country_code or "AR"))
        provinces.add(fold_place(province))
    if len(countries) != 1 or len(provinces) != 1:
        return None
    return Place(country=next(iter(countries)), province=next(iter(provinces)), locality=wanted)


def proximity(country_code: str | None, province: str | None, locality: str | None, place: Place | None) -> float:
    if place is None:
        return 0.0
    event_locality = fold_place(locality)
    event_province = fold_place(province)
    if not event_locality or not event_province:
        return 0.0
    if fold_place(country_code or "AR") != place.country or event_province != place.province:
        return 0.0
    if event_locality == place.locality:
        return 1.0
    return 0.5


def base_score(
    *,
    relevance: float,
    freshness: float,
    proximity_value: float,
    locality_selected: bool,
    weights: PrincipalWeights,
) -> float:
    if not locality_selected:
        total = weights.relevance + weights.freshness
        if total <= 0:
            return 0.0
        return (weights.relevance * relevance + weights.freshness * freshness) / total
    return (
        weights.relevance * relevance
        + weights.freshness * freshness
        + weights.locality * proximity_value
    )


def build_profile(
    event_types: dict[UUID, str | None],
    read_ids: set[UUID],
    like_ids: set[UUID],
    *,
    weights: PrincipalWeights,
) -> AffinityProfile:
    totals: dict[str, float] = {}
    usable = 0
    for event_id in read_ids | like_ids:
        topic = topic_key(event_types.get(event_id))
        if topic is None:
            continue
        signal = 0.0
        if event_id in read_ids:
            signal += weights.read_weight
        if event_id in like_ids:
            signal += weights.like_weight
        if signal <= 0:
            continue
        usable += 1
        totals[topic] = totals.get(topic, 0.0) + signal
    if not totals or weights.confidence_events <= 0:
        return empty_profile()
    peak = max(totals.values())
    if peak <= 0:
        return empty_profile()
    normalized = {topic: value / peak for topic, value in totals.items()}
    confidence = min(1.0, usable / float(weights.confidence_events))
    return AffinityProfile(normalized, confidence)


def affinity_for(event_type: str | None, profile: AffinityProfile) -> float:
    topic = topic_key(event_type)
    if topic is None:
        return 0.0
    return profile.topic_weights.get(topic, 0.0)


def principal_score(base: float, profile: AffinityProfile, event_type: str | None, *, weights: PrincipalWeights) -> float:
    return base + weights.affinity_boost * profile.confidence * affinity_for(event_type, profile)
