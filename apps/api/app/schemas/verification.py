from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from app.domain.enums import ClaimStatus, EvidenceType


class VerificationTarget(StrEnum):
    GENERAL_WEB = "GENERAL_WEB"
    OFFICIAL_RECORD = "OFFICIAL_RECORD"
    OFFICIAL_LAW = "OFFICIAL_LAW"
    OFFICIAL_STATISTICS = "OFFICIAL_STATISTICS"
    JUDICIAL_RECORD = "JUDICIAL_RECORD"
    PRIMARY_STATEMENT = "PRIMARY_STATEMENT"
    ELECTION_AUTHORITY = "ELECTION_AUTHORITY"
    FINANCIAL_OFFICIAL_DATA = "FINANCIAL_OFFICIAL_DATA"
    INDEPENDENT_CORROBORATION = "INDEPENDENT_CORROBORATION"


class TemporalScope(StrEnum):
    CURRENT = "CURRENT"
    RECENT = "RECENT"
    HISTORICAL = "HISTORICAL"
    EXACT_DATE = "EXACT_DATE"
    EXACT_PERIOD = "EXACT_PERIOD"
    TIMELESS = "TIMELESS"


class VerificationSubject(StrEnum):
    GENERAL = "GENERAL"
    GOVERNMENT_APPOINTMENT = "GOVERNMENT_APPOINTMENT"
    STATISTICS = "STATISTICS"
    LAW_OR_DECREE = "LAW_OR_DECREE"
    JUDICIAL_CASE = "JUDICIAL_CASE"
    PUBLIC_STATEMENT = "PUBLIC_STATEMENT"
    ELECTION = "ELECTION"
    FINANCIAL_OFFICIAL = "FINANCIAL_OFFICIAL"
    ACCUSATION = "ACCUSATION"


class EvidenceJudgementType(StrEnum):
    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"
    QUALIFIES = "QUALIFIES"
    MENTIONS = "MENTIONS"
    DOES_NOT_ESTABLISH = "DOES_NOT_ESTABLISH"


PERSISTABLE_JUDGEMENTS = {
    EvidenceJudgementType.SUPPORTS: EvidenceType.SUPPORTS,
    EvidenceJudgementType.CONTRADICTS: EvidenceType.CONTRADICTS,
    EvidenceJudgementType.QUALIFIES: EvidenceType.QUALIFIES,
    EvidenceJudgementType.MENTIONS: EvidenceType.MENTIONS,
}


class VerificationPlan(BaseModel):
    verification_target: VerificationTarget = VerificationTarget.GENERAL_WEB
    temporal_scope: TemporalScope = TemporalScope.TIMELESS
    subject: VerificationSubject = VerificationSubject.GENERAL
    jurisdiction: str = "AR"
    primary_source_required: bool = False
    independent_corroboration_required: bool = False
    year_hint: int | None = None
    search_terms: list[str] = Field(default_factory=list)


class CheapEvidenceJudgement(BaseModel):
    source_ref: int
    relation: EvidenceJudgementType
    excerpt: str | None = None
    confidence: float | None = None
    reason: str | None = None


class CheapClaimEvidenceAssessment(BaseModel):
    judgements: list[CheapEvidenceJudgement] = Field(default_factory=list)
    ambiguous: bool = False
    reason: str | None = None


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


class SearchWindow(BaseModel):
    freshness: str | None = None
    since: datetime | None = None
    until: datetime | None = None
