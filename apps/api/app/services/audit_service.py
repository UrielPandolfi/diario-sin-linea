from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.article_body import block_plain_text, context_claim_ref_map, resolve_article_draft, split_body_paragraphs
from app.core.clock import utc_now
from app.core.config import get_settings
from app.core.prompts import load_prompt
from app.core.usage_context import bind_model_role, usage_scope
from app.domain.enums import ArticleStatus, PipelineStatus
from app.models import Article, Claim, ClaimEvidence, Event, EventSource, PipelineRun, SourceItem
from app.providers.base import ProviderNotConfiguredError, StructuredLLMProvider
from app.providers.rate_limit import is_quota_error, is_transient_rate_limit, openai_error_code
from app.providers.registry import ModelRole, get_structured_provider
from app.repositories import ArticleRepository, EntityRepository, PipelineRunRepository
from app.schemas import ArticleContentUpdate
from app.schemas.auditing import ArticleAuditResult, AuditIssue, AuditIssueSeverity
from app.schemas.writing import ArticleContext, ArticleDraft
from app.services.article_service import ArticleService
from app.services.audit_policy import (
    merge_audit_result,
    structural_blocks_rewrite,
    structural_findings,
)
from app.services.evidence_snapshot import (
    article_context_from_snapshot,
    bind_snapshot_to_version,
    evidence_snapshot_for_version,
)
from app.services.pipeline_lock import AUDITING_STAGE, is_write_audit_publish_busy

AUDITING_ROLE = "auditing"
REWRITE_CHANGE_REASON = "audit_rewrite"


def normalize_audit_result(
    result: ArticleAuditResult,
    *,
    structural: list[AuditIssue] | None = None,
    article: Article | None = None,
    snapshot: dict[str, Any] | None = None,
) -> ArticleAuditResult:
    """LOW nunca bloquea. Findings estructurales no se pueden silenciar con issues=[]."""
    from app.services.audit_policy import merge_audit_result

    return merge_audit_result(result, structural=structural, article=article, snapshot=snapshot)


def _lead_text(article: Article) -> str:
    blocks = article.body_blocks
    if isinstance(blocks, list) and blocks:
        lead = block_plain_text(blocks[0])
        if lead:
            return lead
    parts = split_body_paragraphs(article.body or "")
    return parts[0] if parts else ""


class AuditService:
    def __init__(
        self,
        session: Session,
        *,
        llm: StructuredLLMProvider | None = None,
        writer: StructuredLLMProvider | None = None,
    ) -> None:
        self.session = session
        self.settings = get_settings()
        self.pipeline = PipelineRunRepository(session)
        self.articles = ArticleRepository(session)
        self.entities = EntityRepository(session)
        self.article_service = ArticleService(session)
        self.llm = llm
        self.writer = writer

    def audit(self, event_id: UUID, *, trigger: str, context: dict | None = None) -> dict:
        event = self._load_event(event_id)
        if event is None:
            raise ValueError("event_not_found")
        original_status = event.status

        if is_write_audit_publish_busy(self.pipeline, event_id):
            return {
                "skipped": True,
                "reason": "already_running",
                "event_id": str(event_id),
                "audited": False,
            }

        run = PipelineRun(
            event_id=event.id,
            stage=AUDITING_STAGE,
            status=PipelineStatus.RUNNING,
            metadata_json={"trigger": trigger, "context": context or {}},
        )
        try:
            with self.session.begin_nested():
                self.pipeline.add(run)
                self.session.flush()
        except IntegrityError:
            if run in self.session:
                self.session.expunge(run)
            return {
                "skipped": True,
                "reason": "already_running",
                "event_id": str(event_id),
                "audited": False,
            }

        try:
            with usage_scope(
                stage=AUDITING_STAGE,
                event_id=event.id,
                pipeline_run_id=run.id,
            ):
                result = self._run(event, run, trigger=trigger)
            run.status = PipelineStatus.SUCCESS
            run.finished_at = utc_now()
            run.metadata_json = {**(run.metadata_json or {}), **result}
            event.status = original_status
            self.session.flush()
            self.session.commit()
            return {"skipped": False, "event_id": str(event.id), **result}
        except ProviderNotConfiguredError as exc:
            return self._fail(run, event, original_status, str(exc))
        except Exception as exc:
            extra: dict[str, Any] = {"technical_ok": False, "passed": None, "audited": False}
            if is_quota_error(exc):
                extra["reason"] = "insufficient_quota"
            elif is_transient_rate_limit(exc) or openai_error_code(exc) == "rate_limit_exceeded":
                extra["reason"] = "rate_limit_exceeded"
            return self._fail(run, event, original_status, str(exc), extra=extra)

    def _fail(
        self,
        run: PipelineRun,
        event: Event,
        original_status: Any,
        message: str,
        *,
        extra: dict[str, Any] | None = None,
    ) -> dict:
        run.status = PipelineStatus.FAILED
        run.error_message = message
        run.finished_at = utc_now()
        event.status = original_status
        meta = {**(run.metadata_json or {}), **(extra or {})}
        run.metadata_json = meta
        self.session.flush()
        self.session.commit()
        return {
            "skipped": False,
            "event_id": str(event.id),
            "audited": False,
            "error": message,
            "passed": None,
            **{key: meta[key] for key in ("reason", "technical_ok") if key in meta},
        }

    def _load_event(self, event_id: UUID) -> Event | None:
        stmt = (
            select(Event)
            .execution_options(populate_existing=True)
            .options(
                selectinload(Event.event_sources)
                .selectinload(EventSource.source_item)
                .selectinload(SourceItem.source),
                selectinload(Event.event_entities),
                selectinload(Event.updates),
                selectinload(Event.claims).selectinload(Claim.evidence).selectinload(ClaimEvidence.source_item),
            )
            .where(Event.id == event_id)
        )
        return self.session.scalars(stmt).first()

    def _run(self, event: Event, run: PipelineRun, *, trigger: str) -> dict:
        article = self.articles.get_by_event_id(event.id)
        base: dict[str, Any] = {
            "trigger": trigger,
            "provider": self.settings.auditing_provider,
            "model_role": AUDITING_ROLE,
            "article_id": str(article.id) if article is not None else None,
            "audited": False,
            "passed": None,
            "issues": [],
            "audit_count": 0,
            "rewrite_count": 0,
            "cap_exhausted": False,
            "reason": None,
            "version_before": article.current_version if article is not None else None,
            "version_after": article.current_version if article is not None else None,
        }
        if article is None:
            base["reason"] = "no_article"
            return base
        if article.status not in {ArticleStatus.DRAFT, ArticleStatus.READY_FOR_REVIEW}:
            base["reason"] = "article_not_draft"
            return base

        article_context = None
        snapshot = None
        if article is not None and article.status in {ArticleStatus.DRAFT, ArticleStatus.READY_FOR_REVIEW}:
            runs = self.pipeline.list_for_event(event.id, limit=50)
            snapshot = evidence_snapshot_for_version(runs, article.current_version)
            article_context = article_context_from_snapshot(snapshot)

        cap = self.settings.max_audit_rewrite_cycles
        rewrites = 0
        audits = 0
        auditor = self.llm or get_structured_provider(ModelRole.AUDITING)
        writer = self.writer

        while True:
            bind_model_role(ModelRole.AUDITING.value, provider=self.settings.auditing_provider)
            structural = structural_findings(snapshot, article)
            user_prompt = self._audit_user_prompt(article, article_context, snapshot)
            self.session.commit()
            llm_result = auditor.generate_structured(
                system_prompt=load_prompt("article_audit.md"),
                user_prompt=user_prompt,
                schema=ArticleAuditResult,
            )
            result = normalize_audit_result(
                llm_result,
                structural=structural,
                article=article,
                snapshot=snapshot,
            )
            audits += 1
            rewrite_issues = [
                issue
                for issue in result.issues
                if issue.severity in (AuditIssueSeverity.HIGH, AuditIssueSeverity.MEDIUM)
                and not (issue.reason and structural_blocks_rewrite([issue]))
            ]
            issues = [issue.model_dump(mode="json") for issue in result.issues]
            bound_snapshot = bind_snapshot_to_version(snapshot, article.current_version) if snapshot else None
            base.update(
                {
                    "audited": True,
                    "passed": result.passed,
                    "editorial_passed": result.editorial_passed,
                    "issues": issues,
                    "audit_count": audits,
                    "rewrite_count": rewrites,
                    "version_after": article.current_version,
                    "structural_issue_count": len(structural),
                    "claims_fingerprint": (snapshot or {}).get("claims_fingerprint"),
                    "coverage_run_id": (snapshot or {}).get("coverage_run_id"),
                    "verification_run_id": (snapshot or {}).get("verification_run_id"),
                    "evidence_snapshot": bound_snapshot,
                    "technical_ok": True,
                }
            )
            run.metadata_json = {**(run.metadata_json or {}), **base}
            self.session.flush()

            tolerance = [
                issue
                for issue in result.issues
                if "tolerada por la política editorial" in (issue.explanation or "")
            ]
            if tolerance:
                base["headline_attribution_tolerance"] = True
                base["headline_attribution_tolerance_claim_ids"] = [
                    issue.claim_id for issue in tolerance if issue.claim_id
                ]
            if result.passed:
                base["reason"] = "passed"
                base["cap_exhausted"] = False
                article.status = ArticleStatus.READY_FOR_REVIEW
                self.session.flush()
                return base

            if structural_blocks_rewrite(result.issues):
                base["reason"] = "structural_block"
                base["cap_exhausted"] = False
                base["passed"] = False
                article.status = ArticleStatus.DRAFT
                return base

            # Cap = rewrites máximos. El rewrite #cap se audita en la
            # siguiente iteración antes de poder devolver cap_exhausted.
            if rewrites >= cap:
                base["reason"] = "cap_exhausted"
                base["cap_exhausted"] = True
                base["passed"] = False
                article.status = ArticleStatus.DRAFT
                return base

            if writer is None:
                writer = get_structured_provider(ModelRole.WRITING)
            bind_model_role(ModelRole.WRITING.value, provider=self.settings.writing_provider)
            if article_context is None:
                raise RuntimeError("article_context_missing_for_rewrite")
            rewrite_prompt = self._rewrite_user_prompt(article_context, article, rewrite_issues)
            self.session.commit()
            draft = writer.generate_structured(
                system_prompt=load_prompt("article_writing.md"),
                user_prompt=rewrite_prompt,
                schema=ArticleDraft,
            )
            body, body_blocks = resolve_article_draft(
                draft, claim_ref_map=context_claim_ref_map(article_context)
            )
            article = self.articles.lock_by_id(article.id) or article
            article = self.article_service.update_content(
                article,
                ArticleContentUpdate(
                    headline=draft.headline,
                    summary=draft.summary,
                    body=body,
                    body_blocks=body_blocks,
                    change_reason=REWRITE_CHANGE_REASON,
                ),
            )
            rewrites += 1
            if snapshot is not None:
                snapshot = bind_snapshot_to_version(snapshot, article.current_version)
            base["rewrite_count"] = rewrites
            base["version_after"] = article.current_version
            base["evidence_snapshot"] = snapshot
            run.metadata_json = {**(run.metadata_json or {}), **base}
            self.session.flush()
            self.session.commit()
            self.session.refresh(run)
            self.session.refresh(event)
            article = self.articles.get_by_event_id(event.id)
            if article is None:
                raise RuntimeError("article_missing_after_rewrite")

        raise RuntimeError("audit_loop_escaped")

    def _audit_user_prompt(
        self,
        article: Article,
        article_context: ArticleContext | None = None,
        snapshot: dict[str, Any] | None = None,
    ) -> str:
        payload = {
            "headline": article.headline,
            "summary": article.summary,
            "body": article.body,
            "body_blocks": article.body_blocks,
        }
        if article_context is not None:
            from app.services.audit_policy import _claim_ids_from_blocks
            used = set(_claim_ids_from_blocks(article.body_blocks))
            claims = [claim for bucket in (article_context.confirmed_claims, article_context.single_source_claims,
                       article_context.conflicting_claims, article_context.uncertain_claims,
                       article_context.disproven_claims, article_context.outdated_claims) for claim in bucket]
            related = {cid for claim in claims if claim.id in used for cid in claim.related_claim_ids}
            decisions = (snapshot or {}).get("decision_by_claim_id") if isinstance(snapshot, dict) else {}
            if not isinstance(decisions, dict):
                decisions = {}

            def compact(claim):
                decision = decisions.get(claim.id) if isinstance(decisions.get(claim.id), dict) else {}
                basis = claim.support_basis.model_dump(
                    exclude={"document_keys", "information_origins", "evaluated_canonical_text"}
                ) if claim.support_basis else None
                return {
                    "claim_id": claim.id, "claim_ref": claim.ref, "canonical_text": claim.canonical_text,
                    "claim_type": claim.claim_type, "importance": claim.importance.value,
                    "status": claim.status.value, "proposition_role": claim.proposition_role,
                    "final_reason": claim.final_reason, "related_claim_ids": claim.related_claim_ids,
                    "support_basis": basis,
                    "evaluation_state": decision.get("evaluation_state"),
                    "public_rendering": decision.get("public_rendering"),
                    "verified_scope": decision.get("verified_scope"),
                    "unsupported_scope": decision.get("unsupported_scope"),
                }
            payload["evidence_posture"] = [compact(c) for c in claims if c.id in used | related]
            # Headline/summary have no claim_refs in the current contract. These
            # compact candidates let Audit identify their claims without new I/O.
            payload["headline_claim_candidates"] = [compact(c) for c in claims if c.id not in used | related]
        payload["lead"] = _lead_text(article)
        extra = ""
        if article.published_version is not None:
            extra = (
                "Esta es una candidata de actualización. Validala contra evidence_posture de esta versión, "
                "no contra el artículo live anterior. La excepción de omisión en el titular solo aplica "
                "si se cumplen todas sus condiciones. No trates un claim DISPROVEN como error por el solo "
                "hecho de aparecer, si el texto lo atribuye y explica la refutación.\n"
            )
        return (
            extra
            + "Aplicá las reglas del sistema. No verifiques hechos. No reescribas el artículo; devolvé passed e issues. "
            "Una atribución en el cuerpo no cubre otra afirmación del titular, la bajada o el lead. "
            "La excepción de omisión en el titular solo aplica si se cumplen todas sus condiciones. "
            "Los candidatos adicionales solo sirven si se usan en titular o bajada; no exijas incluirlos. "
            "No inventes evaluation_state, public_rendering ni scopes ausentes.\n"
            + json.dumps(payload, ensure_ascii=False)
        )

    def _rewrite_user_prompt(self, article_context: ArticleContext, article: Article, issues: list[AuditIssue]) -> str:
        payload = {
            "context": json.loads(article_context.model_dump_json()),
            "draft": {
                "headline": article.headline,
                "summary": article.summary,
                "body": article.body,
                "body_blocks": article.body_blocks,
            },
            "issues": [issue.model_dump(mode="json") for issue in issues],
        }
        return (
            "Corregí el sesgo o el exceso de certeza señalado, respetando el support_basis del snapshot. "
            "Si el exceso está en titular, bajada o lead, atribuí o calificá ahí; no borres el dato. "
            "Preservá datos, citas literales y atribuciones. "
            "No neutralices declaraciones claramente atribuidas. "
            "No inventes hechos ni uses el context para reabrir verificación factual. "
            "Devolvé body_blocks con claim_refs C1/C2, nunca UUIDs.\n\n"
            + json.dumps(payload, ensure_ascii=False)
        )
