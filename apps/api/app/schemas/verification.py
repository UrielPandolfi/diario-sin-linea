from pydantic import BaseModel, Field

from app.domain.enums import ClaimStatus, EvidenceType


class VerificationEvidence(BaseModel):
    source_ref: int
    evidence_type: EvidenceType
    excerpt: str | None = None
    confidence: float | None = None


class VerificationResult(BaseModel):
    status: ClaimStatus
    confidence: float | None = None
    evidence: list[VerificationEvidence] = Field(default_factory=list)
    reason: str | None = None
    unresolved: bool = False
