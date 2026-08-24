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
    MATERIAL_OMISSION = "MATERIAL_OMISSION"


class AuditIssueSeverity(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class AuditIssue(BaseModel):
    type: AuditIssueType
    severity: AuditIssueSeverity
    text: str
    explanation: str
    suggested_fix: str | None = None


class ArticleAuditResult(BaseModel):
    passed: bool
    issues: list[AuditIssue] = Field(default_factory=list)
