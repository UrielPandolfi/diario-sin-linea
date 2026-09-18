from typing import Literal

from pydantic import BaseModel


class Measurement(BaseModel):
    """Coordinates of ONE observation, grounded in the associated literal fragment."""

    indicator: str
    unit: str
    scope: str
    period: str
    value: str


class EvidenceComparison(BaseModel):
    proposition: Literal["statement", "statistic", "other"]
    claim_fragment: str
    evidence_fragment: str
    basis: Literal["explicit_negation", "incompatible_value", "same_value", "partial_support"]
    claim_measurement: Measurement | None = None
    evidence_measurement: Measurement | None = None
    approximation: Literal["compatible", "incompatible", "unknown"] = "unknown"
    # Contextual explanation, not a universal percentage tolerance.
    approximation_reason: str | None = None
    reason: str
