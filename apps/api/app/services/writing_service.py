from __future__ import annotations

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
from app.models import Claim, ClaimEvidence, Event, EventSource, PipelineRun, SourceItem
from app.providers.base import ProviderNotConfiguredError, StructuredLLMProvider
from app.providers.registry import ModelRole, get_structured_provider
from app.repositories import ArticleRepository, EntityRepository, PipelineRunRepository
from app.schemas import ArticleContentUpdate, ArticleCreate
from app.schemas.writing import ArticleDraft
from app.services.article_context import build_article_context, last_success_run
from app.services.article_service import ArticleService
from app.services.evidence_snapshot import capture_evidence_snapshot, persist_snapshot_fields
from app.services.material_change import detect_material_change, snapshot_claims
from app.services.pipeline_lock import WRITING_STAGE, is_write_audit_publish_busy
from app.services.verification_outcome import pair_from_runs

WRITING_ROLE = "writing"


class WritingService:
    def __init__(
        self,
        session: Session,
        *,
        llm: StructuredLLMProvider | None = None,
    ) -> None:
        self.session = session
        self.settings = get_settings()
        self.pipeline = PipelineRunRepository(session)
        self.articles = ArticleRepository(session)
        self.entities = EntityRepository(session)
        self.article_service = ArticleService(session)
        self.llm = llm

    def write(self, event_id: UUID, *, trigger: str, context: dict | None = None) -> dict:
        event = self._load_event(event_id)
        if event is None:
            raise ValueError("event_not_found")
        original_status = event.status

        if is_write_audit_publish_busy(self.pipeline, event_id):
            return {
                "skipped": True,
                "reason": "already_running",
                "event_id": str(event_id),
                "written": False,
            }

        run = PipelineRun(
            event_id=event.id,
            stage=WRITING_STAGE,
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
                "written": False,
            }

        try:
            with usage_scope(
                stage=WRITING_STAGE,
                event_id=event.id,
                pipeline_run_id=run.id,
            ):
                result = self._run(event, trigger=trigger)
            run.status = PipelineStatus.SUCCESS
            run.finished_at = utc_now()
            run.metadata_json = {**(run.metadata_json or {}), **result}
            event.status = original_status
            self.session.flush()
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
        return {
            "skipped": False,
            "event_id": str(event.id),
            "written": False,
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

    def _run(self, event: Event, *, trigger: str) -> dict:
        claims_snapshot = snapshot_claims(list(event.claims))
        base = {
            "trigger": trigger,
            "claims_snapshot": claims_snapshot,
            "material_reasons": [],
            "provider": self.settings.writing_provider,
            "model_role": WRITING_ROLE,
            "article_id": None,
            "created": False,
            "written": False,
            "reason": None,
            "version": None,
        }
        if not event.claims:
            base["reason"] = "no_claims"
            return base

        article = self.articles.lock_by_event_id(event.id)
        if article is not None and not self._can_write(article):
            base["article_id"] = str(article.id)
            base["version"] = article.current_version
            base["reason"] = "article_not_draft"
            return base

        previous = None
        if article is not None:
            previous_run = last_success_run(
                self.pipeline.list_for_event(event.id, limit=50), WRITING_STAGE
            )
            if previous_run is not None:
                previous = (previous_run.metadata_json or {}).get("claims_snapshot") or []

        change = detect_material_change(previous, claims_snapshot)
        if article is not None and not change.is_material:
            base["article_id"] = str(article.id)
            base["version"] = article.current_version
            base["reason"] = "no_material_change"
            base["material_reasons"] = change.reasons
            return base

        pipeline_runs = self.pipeline.list_for_event(event.id, limit=50)
        article_context = build_article_context(
            event,
            entities=self.entities.list_for_event(event.id),
            pipeline_runs=pipeline_runs,
            max_claims=self.settings.max_writing_claims_per_event,
            max_sources=self.settings.max_writing_sources_per_event,
            excerpt_chars=self.settings.writing_excerpt_chars,
            max_source_contexts=self.settings.max_writing_source_contexts,
            source_context_chars=self.settings.writing_source_context_chars,
        )
        claim_run, verify_run = pair_from_runs(list(pipeline_runs))
        evidence_snapshot = capture_evidence_snapshot(article_context, claim_run, verify_run)
        llm = self.llm or get_structured_provider(ModelRole.WRITING)
        bind_model_role(ModelRole.WRITING.value, provider=self.settings.writing_provider)
        draft = llm.generate_structured(
            system_prompt=load_prompt("article_writing.md"),
            user_prompt=self._user_prompt(article_context),
            schema=ArticleDraft,
        )
        body, body_blocks = resolve_article_draft(
            draft, claim_ref_map=context_claim_ref_map(article_context)
        )
        change_reason = "initial" if article is None else ",".join(change.reasons) or "material_change"
        if article is None:
            article, created = self.article_service.create_draft(
                ArticleCreate(
                    event_id=event.id,
                    headline=draft.headline,
                    summary=draft.summary,
                    body=body,
                    body_blocks=body_blocks,
                    status=ArticleStatus.DRAFT,
                )
            )
        else:
            created = False
            article = self.article_service.update_content(
                article,
                ArticleContentUpdate(
                    headline=draft.headline,
                    summary=draft.summary,
                    body=body,
                    body_blocks=body_blocks,
                    change_reason=change_reason,
                ),
            )
            if article.status == ArticleStatus.PUBLISHED:
                article.status = ArticleStatus.DRAFT
            self.session.flush()
        evidence_snapshot["version"] = article.current_version
        base.update(
            {
                "article_id": str(article.id),
                "created": created,
                "written": True,
                "reason": change_reason,
                "version": article.current_version,
                "material_reasons": change.reasons,
            }
        )
        base.update(persist_snapshot_fields(evidence_snapshot))
        return base

    def _can_write(self, article) -> bool:
        if article.status == ArticleStatus.DRAFT:
            return True
        return article.status == ArticleStatus.PUBLISHED and article.published_version is not None

    def _article_context(self, event: Event):
        return build_article_context(
            event,
            entities=self.entities.list_for_event(event.id),
            pipeline_runs=self.pipeline.list_for_event(event.id, limit=50),
            max_claims=self.settings.max_writing_claims_per_event,
            max_sources=self.settings.max_writing_sources_per_event,
            excerpt_chars=self.settings.writing_excerpt_chars,
            max_source_contexts=self.settings.max_writing_source_contexts,
            source_context_chars=self.settings.writing_source_context_chars,
        )

    def _user_prompt(self, article_context) -> str:
        weak = [
            f"{claim.ref} ({claim.status.value}): {claim.canonical_text}"
            for claim in (*article_context.single_source_claims, *article_context.uncertain_claims)
        ]
        reminder = ""
        if weak:
            reminder = (
                "Claims SINGLE_SOURCE o UNCERTAIN: no los escribas como hecho de Sin Línea; "
                "atribución explícita, incertidumbre, u omisión.\n"
                + "\n".join(weak)
                + "\n\n"
            )
        coverage_gap = bool(getattr(article_context.verification, "coverage_gap", False))
        if coverage_gap:
            reminder += (
                "Hay un hueco de cobertura: el título o el lead del suceso no tiene un Claim "
                "equivalente persistido. No afirmes event.working_title como hecho de Sin Línea. "
                "Atribuir no cierra el hueco.\n\n"
            )
        if getattr(article_context.verification, "stale_verification", False):
            reminder += (
                "La verificación está desparejada o ausente. No afirmes hechos centrales como "
                "comprobados de Sin Línea.\n\n"
            )
        if getattr(article_context.verification, "verification_incomplete", False) or getattr(
            article_context.verification, "central_unverified", None
        ):
            reminder += (
                "Hay claims centrales pendientes de verificación. No los presentes como acreditados.\n\n"
            )
        return (
            "Redactá a partir de este ArticleContext JSON. "
            "El suceso a cubrir es event.working_title; no conviertas otro hecho del mismo día en el titular. "
            "No uses fuentes ni claims que no estén listados. "
            "source_contexts son narrativa de lo ya cubierto: no introduzcas hechos materiales nuevos. "
            "Atribuir ('según X') solo si hay claim/evidencia evaluada de que esa fuente dijo o reportó lo afirmado. "
            "En body_blocks usá claim_refs C1/C2 del context, nunca UUIDs.\n"
            + reminder
            + "\n"
            + article_context.model_dump_json()
        )
