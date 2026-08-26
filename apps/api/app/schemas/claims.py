from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, Field

from app.domain.enums import ClaimImportance, ClaimStatus, EvidenceType


def _coerce_optional_str(value: Any) -> str | None:
    """Los LLM suelen devolver cifras como int/float; el schema y la DB usan str."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, (int, float)):
        return str(value)
    return str(value)


OptionalStr = Annotated[str | None, BeforeValidator(_coerce_optional_str)]


class ExtractedEvidence(BaseModel):
    source_ref: int
    evidence_type: EvidenceType
    excerpt: str | None = None
    confidence: float | None = None


class ExtractedClaim(BaseModel):
    canonical_text: str
    claim_type: str | None = None
    importance: ClaimImportance = ClaimImportance.MEDIUM
    subject: str | None = None
    predicate: str | None = None
    object_text: str | None = None
    normalized_value: OptionalStr = None
    unit: str | None = None
    occurred_at: datetime | None = None
    evidence: list[ExtractedEvidence] = Field(default_factory=list)


class ClaimExtractionBatch(BaseModel):
    claims: list[ExtractedClaim] = Field(default_factory=list)


class ClaimResolutionItem(BaseModel):
    claim_ref: int
    status: ClaimStatus
    confidence: float | None = None
    conflicts: list[str] = Field(default_factory=list)
    needs_external_verification: bool = False
    reason: str | None = None


class ClaimResolutionBatch(BaseModel):
    items: list[ClaimResolutionItem] = Field(default_factory=list)
