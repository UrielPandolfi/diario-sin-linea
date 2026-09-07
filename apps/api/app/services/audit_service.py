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
from app.providers.registry import ModelRole, get_structured_provider
from app.repositories import ArticleRepository, EntityRepository, PipelineRunRepository
from app.schemas import ArticleContentUpdate
from app.schemas.auditing import ArticleAuditResult, AuditIssue, AuditIssueSeverity
from app.schemas.writing import ArticleDraft
from app.services.article_context import build_article_context
from app.services.article_service import ArticleService
from app.services.pipeline_lock import AUDITING_STAGE, is_write_audit_publish_busy

AUDITING_ROLE = "auditing"
REWRITE_CHANGE_REASON = "audit_rewrite"


def normalize_audit_result(result: ArticleAuditResult) -> ArticleAuditResult:
    """LOW nunca bloquea: passed=false solo con issues HIGH o MEDIUM."""
    blocking = [
        issue
        for issue in result.issues
        if issue.severity in (AuditIssueSeverity.HIGH, AuditIssueSeverity.MEDIUM)
    ]
    return ArticleAuditResult(passed=not blocking, issues=list(result.issues))


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
            return self._fail(run, event, original_status, str(exc))

    def _fail(self, run: PipelineRun, event: Event, original_status: Any, message: str) -> dict:
        run.status = PipelineStatus.FAILED
        run.error_message = message
        run.finished_at = utc_now()
        event.status = original_status
        self.session.flush()
        self.session.commit()
        return {
            "skipped": False,
            "event_id": str(event.id),
            "audited": False,
            "error": message,
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

        article_context = build_article_context(
            event,
            entities=self.entities.list_for_event(event.id),
            pipeline_runs=self.pipeline.list_for_event(event.id, limit=50),
            max_claims=self.settings.max_writing_claims_per_event,
            max_sources=self.settings.max_writing_sources_per_event,
            excerpt_chars=self.settings.writing_excerpt_chars,
            max_source_contexts=self.settings.max_writing_source_contexts,
            source_context_chars=self.settings.writing_source_context_chars,
        )
        cap = self.settings.max_audit_rewrite_cycles
        rewrites = 0
        audits = 0
        auditor = self.llm or get_structured_provider(ModelRole.AUDITING)
        writer = self.writer

        while True:
            bind_model_role(ModelRole.AUDITING.value, provider=self.settings.auditing_provider)
            result = normalize_audit_result(
                auditor.generate_structured(
                    system_prompt=load_prompt("article_audit.md"),
                    user_prompt=self._audit_user_prompt(article_context, article),
                    schema=ArticleAuditResult,
                )
            )
            audits += 1
            # Solo issues bloqueantes alimentan el rewrite; LOW no dispara otro ciclo.
            rewrite_issues = [
                issue
                for issue in result.issues
                if issue.severity in (AuditIssueSeverity.HIGH, AuditIssueSeverity.MEDIUM)
            ]
            issues = [issue.model_dump(mode="json") for issue in result.issues]
            base.update(
                {
                    "audited": True,
                    "passed": result.passed,
                    "issues": issues,
                    "audit_count": audits,
                    "rewrite_count": rewrites,
                    "version_after": article.current_version,
                }
            )
            run.metadata_json = {**(run.metadata_json or {}), **base}
            self.session.flush()

            if result.passed:
                base["reason"] = "passed"
                base["cap_exhausted"] = False
                return base

            if rewrites >= cap:
                base["reason"] = "cap_exhausted"
                base["cap_exhausted"] = True
                base["passed"] = False
                return base

            if writer is None:
                writer = get_structured_provider(ModelRole.WRITING)
            bind_model_role(ModelRole.WRITING.value, provider=self.settings.writing_provider)
            draft = writer.generate_structured(
                system_prompt=load_prompt("article_writing.md"),
                user_prompt=self._rewrite_user_prompt(article_context, article, rewrite_issues),
                schema=ArticleDraft,
            )
            body, body_blocks = resolve_article_draft(
                draft, claim_ref_map=context_claim_ref_map(article_context)
            )
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
            base["rewrite_count"] = rewrites
            base["version_after"] = article.current_version
            run.metadata_json = {**(run.metadata_json or {}), **base}
            self.session.flush()
            self.session.commit()
            self.session.refresh(run)
            self.session.refresh(event)
            article = self.articles.get_by_event_id(event.id)
            if article is None:
                raise RuntimeError("article_missing_after_rewrite")

        raise RuntimeError("audit_loop_escaped")

    def _audit_user_prompt(self, article_context, article: Article) -> str:
        payload = {
            "context": json.loads(article_context.model_dump_json()),
            "draft": {
                "headline": article.headline,
                "summary": article.summary,
                "body": article.body,
                "body_blocks": article.body_blocks,
            },
        }
        weak = [
            f"{claim.ref} ({claim.status.value}): {claim.canonical_text}"
            for claim in (*article_context.single_source_claims, *article_context.uncertain_claims)
        ]
        reminder = ""
        if weak:
            reminder = (
                "Claims SINGLE_SOURCE o UNCERTAIN: si el draft los afirma como hecho de Sin Línea "
                "sin atribución explícita ni incertidumbre, reportá ATTRIBUTION.\n"
                + "\n".join(weak)
                + "\n\n"
            )
        return (
            "Audita este draft contra el ArticleContext JSON. "
            "No reescribas el artículo; devolvé passed e issues. "
            "Revisá también body_blocks y las annotations de claims.\n"
            + reminder
            + "\n"
            + json.dumps(payload, ensure_ascii=False)
        )

    def _rewrite_user_prompt(self, article_context, article: Article, issues: list[AuditIssue]) -> str:
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
            "Devolvé body_blocks con claim_refs C1/C2, nunca UUIDs.\n\n"
            + json.dumps(payload, ensure_ascii=False)
        )
