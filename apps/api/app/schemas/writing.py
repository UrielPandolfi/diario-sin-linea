from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.domain.enums import ClaimImportance, ClaimStatus, EntityType, EventSourceRelation, EvidenceType


class ArticleDraftSegment(BaseModel):
    text: str = Field(min_length=1)
    claim_refs: list[str] = Field(default_factory=list)


class ArticleDraftBlock(BaseModel):
    type: Literal["paragraph"] = "paragraph"
    segments: list[ArticleDraftSegment] = Field(min_length=1)


class ArticleDraft(BaseModel):
    headline: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    body_blocks: list[ArticleDraftBlock] = Field(min_length=1)


class PersistedBodySegment(BaseModel):
    text: str
    claim_ids: list[str] = Field(default_factory=list)


class PersistedBodyBlock(BaseModel):
    type: Literal["paragraph"] = "paragraph"
    segments: list[PersistedBodySegment] = Field(default_factory=list)


class ContextEvidence(BaseModel):
    source_ref: int
    evidence_type: EvidenceType
    excerpt: str | None = None


class ContextSource(BaseModel):
    ref: int
    name: str
    domain: str | None = None
    url: str
    title: str | None = None
    relation_type: EventSourceRelation
    is_primary: bool = False
    is_monitored: bool = False


class ContextSourceText(BaseModel):
    source_id: str
    source_name: str
    url: str
    title: str | None = None
    published_at: datetime | None = None
    text: str


class ContextClaim(BaseModel):
    id: str
    ref: str
    canonical_text: str
    claim_type: str | None = None
    importance: ClaimImportance
    status: ClaimStatus
    subject: str | None = None
    predicate: str | None = None
    object_text: str | None = None
    normalized_value: str | None = None
    unit: str | None = None
    occurred_at: datetime | None = None
    evidence: list[ContextEvidence] = Field(default_factory=list)


class ContextEntity(BaseModel):
    name: str
    entity_type: EntityType | str
    role: str


class ContextEventStub(BaseModel):
    event_id: str
    event_type: str
    working_title: str
    locality: str | None = None
    province: str | None = None
    neighborhood: str | None = None
    started_at: datetime | None = None
    short_summary: str | None = None


class ContextTimelineItem(BaseModel):
    occurred_at: datetime | None = None
    text: str
    kind: str


class ContextVerificationSol(BaseModel):
    claim_id: str
    status_before: str | None = None
    status_after: str | None = None
    unresolved: bool | None = None
    reason: str | None = None


class ContextVerification(BaseModel):
    selected: list[dict] = Field(default_factory=list)
    sol: list[ContextVerificationSol] = Field(default_factory=list)


class ArticleContext(BaseModel):
    event: ContextEventStub
    confirmed_claims: list[ContextClaim] = Field(default_factory=list)
    single_source_claims: list[ContextClaim] = Field(default_factory=list)
    conflicting_claims: list[ContextClaim] = Field(default_factory=list)
    uncertain_claims: list[ContextClaim] = Field(default_factory=list)
    disproven_claims: list[ContextClaim] = Field(default_factory=list)
    outdated_claims: list[ContextClaim] = Field(default_factory=list)
    entities: list[ContextEntity] = Field(default_factory=list)
    timeline: list[ContextTimelineItem] = Field(default_factory=list)
    sources: list[ContextSource] = Field(default_factory=list)
    source_contexts: list[ContextSourceText] = Field(default_factory=list)
    claim_refs: dict[str, str] = Field(default_factory=dict)
    verification: ContextVerification = Field(default_factory=ContextVerification)


class ClaimSnapshot(BaseModel):
    id: str
    canonical_text: str
    status: str
    importance: str
    normalized_value: str | None = None
    claim_type: str | None = None
