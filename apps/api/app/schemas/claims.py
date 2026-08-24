from datetime import datetime

from pydantic import BaseModel, Field

from app.domain.enums import ClaimImportance, ClaimStatus, EvidenceType


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
    normalized_value: str | None = None
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
