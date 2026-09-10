from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.article_body import context_claim_ref_map, resolve_article_draft
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
    heuristic_signals,
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
) -> ArticleAuditResult:
    """LOW nunca bloquea. Findings estructurales no se pueden silenciar con issues=[]."""
    from app.services.audit_policy import merge_audit_result

    return merge_audit_result(result, structural=structural)


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
        if article.status != ArticleStatus.DRAFT:
            base["reason"] = "article_not_draft"
            return base

        article_context = None
        snapshot = None
        if article is not None and article.status == ArticleStatus.DRAFT:
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
            user_prompt = self._audit_user_prompt(article_context, article, snapshot, structural)
            self.session.commit()
            llm_result = auditor.generate_structured(
                system_prompt=load_prompt("article_audit.md"),
                user_prompt=user_prompt,
                schema=ArticleAuditResult,
            )
            result = normalize_audit_result(llm_result, structural=structural)
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

            if result.passed:
                base["reason"] = "passed"
                base["cap_exhausted"] = False
                return base

            if structural_blocks_rewrite(structural):
                base["reason"] = "structural_block"
                base["cap_exhausted"] = False
                base["passed"] = False
                return base

            if rewrites >= cap:
                base["reason"] = "cap_exhausted"
                base["cap_exhausted"] = True
                base["passed"] = False
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
        article_context: ArticleContext | None,
        article: Article,
        snapshot: dict | None,
        structural: list[AuditIssue],
    ) -> str:
        context_payload = json.loads(article_context.model_dump_json()) if article_context is not None else None
        evidence_meta = None
        if snapshot is not None:
            evidence_meta = {
                key: snapshot.get(key)
                for key in (
                    "contract_version",
                    "coverage_run_id",
                    "verification_run_id",
                    "based_on_claim_run_id",
                    "claims_fingerprint",
                    "coverage",
                    "decision_by_claim_id",
                    "verification_incomplete",
                    "central_unverified",
                    "stale_verification",
                    "version",
                )
            }
        payload = {
            "context": context_payload,
            "draft": {
                "headline": article.headline,
                "summary": article.summary,
                "body": article.body,
                "body_blocks": article.body_blocks,
            },
            "evidence_snapshot": evidence_meta,
            "structural_findings": [issue.model_dump(mode="json") for issue in structural],
            "heuristic_signals": heuristic_signals(article),
        }
        weak = []
        if article_context is not None:
            weak = [
                f"{claim.ref} ({claim.status.value}): {claim.canonical_text}"
                for claim in (*article_context.single_source_claims, *article_context.uncertain_claims)
            ]
        reminder = (
            "Los findings estructurales ya están decididos: no los silencies. "
            "heuristic_signals son pistas: respetá negación, atribución y alcance; no las trates como HIGH automáticos. "
            "source_contexts no autorizan hechos materiales nuevos. "
            "Atribuir no valida un hecho si el snapshot no tiene claim/evidencia pertinente. "
            "No recalcules SUPPORTED/SINGLE_SOURCE: usá decision_by_claim_id y support_basis.\n"
        )
        if weak:
            reminder += (
                "Claims SINGLE_SOURCE o UNCERTAIN: si el draft los afirma como hecho de Sin Línea "
                "sin atribución explícita ni incertidumbre, reportá ATTRIBUTION.\n"
                + "\n".join(weak)
                + "\n\n"
            )
        return (
            "Audita este draft contra el snapshot de evidencia de ESTA versión. "
            "No reescribas el artículo; devolvé passed e issues. "
            "Revisá también body_blocks y las annotations de claims.\n"
            + reminder
            + "\n"
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
            "Corregí el draft según estos issues de auditoría. "
            "No inventes claims fuera del context. "
            "Asociá a un claim/evidencia ya evaluada, retiralo, o dejalo para revisión. "
            "Anteponer 'según X' solo vale si el snapshot prueba que esa fuente dijo o reportó lo afirmado. "
            "Atribuir no cierra un coverage_gap central. "
            "Devolvé body_blocks con claim_refs C1/C2, nunca UUIDs.\n\n"
            + json.dumps(payload, ensure_ascii=False)
        )
