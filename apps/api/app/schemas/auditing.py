from enum import StrEnum

from pydantic import BaseModel, Field


class AuditIssueType(StrEnum):
    UNSUPPORTED_CLAIM = "UNSUPPORTED_CLAIM"
    NUMBER = "NUMBER"
    NAME = "NAME"
    DATE = "DATE"
    ATTRIBUTION = "ATTRIBUTION"
    CONTRADICTION = "CONTRADICTION"
    CAUSALITY = "CAUSALITY"
    INFERENCE = "INFERENCE"
    FRAMING = "FRAMING"
    ADJECTIVE = "ADJECTIVE"
    UNATTRIBUTED_CHARACTERIZATION = "UNATTRIBUTED_CHARACTERIZATION"
    MATERIAL_OMISSION = "MATERIAL_OMISSION"
    INVALID_CLAIM_MAPPING = "INVALID_CLAIM_MAPPING"
    UNMAPPED_MATERIAL_CLAIM = "UNMAPPED_MATERIAL_CLAIM"
    REDUNDANCY = "REDUNDANCY"
    CLARITY = "CLARITY"


class AuditIssueSeverity(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class AuditIssueReason(StrEnum):
    CENTRAL_UNCOVERED = "central_uncovered"
    CONTRACT_MISSING = "contract_missing"
    CONTRACT_UNPAIRED = "contract_unpaired"
    CENTRAL_UNVERIFIED = "central_unverified"
    PARTIAL_AS_TOTAL = "partial_as_total"
    SINGLE_AS_CORROBORATED = "single_as_corroborated"
    ATTRIBUTION_LOST = "attribution_lost"
    SEMANTIC_SHIFT = "semantic_shift"
    UNBACKED_MATERIAL = "unbacked_material"
    UTTERANCE_AS_TRUTH = "utterance_as_truth"
    NORM_EFFECTIVE_AS_FACT = "norm_effective_as_fact"
    ACCUSATION_AS_FACT = "accusation_as_fact"
    INVALID_CLAIM_REF = "invalid_claim_ref"


class AuditIssueAction(StrEnum):
    ATTRIBUTE = "attribute"
    DROP = "drop"
    REWRITE = "rewrite"
    REVIEW = "review"


class AuditIssue(BaseModel):
    type: AuditIssueType
    severity: AuditIssueSeverity
    text: str
    explanation: str
    suggested_fix: str | None = None
    reason: AuditIssueReason | None = None
    claim_ref: str | None = None
    claim_id: str | None = None
    action: AuditIssueAction | None = None


class ArticleAuditResult(BaseModel):
    passed: bool
    issues: list[AuditIssue] = Field(default_factory=list)
    editorial_passed: bool | None = None
