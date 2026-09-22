from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.article_body import claim_ids_in_body_blocks, context_claim_ref_map, resolve_article_draft
from app.core.clock import utc_now
from app.core.config import get_settings
from app.core.prompts import load_prompt
from app.core.usage_context import bind_model_role, usage_scope
from app.domain.enums import ArticleStatus, ClaimStatus, PipelineStatus
from app.models import Article, Claim, ClaimEvidence, Event, EventSource, PipelineRun, SourceItem
from app.providers.base import ProviderNotConfiguredError, StructuredLLMProvider
from app.providers.registry import ModelRole, get_structured_provider
from app.repositories import ArticleRepository, EntityRepository, PipelineRunRepository
from app.schemas import ArticleContentUpdate, ArticleCreate
from app.schemas.writing import ArticleDraft
from app.services.article_context import (
    build_article_context,
    claims_snapshot_for_version,
    last_written_run,
)
from app.services.article_service import ArticleService
from app.services.claim_coverage import build_coverage_contract
from app.services.claim_service import comparison_key_for
from app.services.evidence_snapshot import (
    capture_evidence_snapshot,
    evidence_snapshot_for_version,
    pair_completes_skipped_claims,
    persist_snapshot_fields,
    snapshot_lacks_usable_verification,
)
from app.services.material_change import build_knowledge_delta, detect_material_change, snapshot_claims
from app.services.pipeline_lock import AUDITING_STAGE, WRITING_STAGE, is_write_audit_publish_busy
from app.services.verification_outcome import pair_from_runs

WRITING_ROLE = "writing"


def confirmation_dropped(previous: list | None, current: list) -> bool:
    """True when a previously corroborated claim is no longer SUPPORTED."""
    if not previous:
        return False
    prev = {
        str(row.get("id")): row
        for row in previous
        if isinstance(row, dict) and row.get("id")
    }
    for row in current:
        if not isinstance(row, dict) or not row.get("id"):
            continue
        before = prev.get(str(row["id"]))
        if before is None:
            continue
        if (
            str(before.get("status") or "") == ClaimStatus.SUPPORTED.value
            and str(row.get("status") or "") != ClaimStatus.SUPPORTED.value
        ):
            return True
    return False


def live_coverage_gap(event: Event) -> bool:
    try:
        return bool(
            build_coverage_contract(event=event, claims=list(event.claims), dropped=[]).coverage_gap
        )
    except Exception:
        return False

_UPDATE_INSTRUCTIONS = (
    "El artículo publicado anterior es una base editorial, no una fuente factual. "
    "Conservá el texto que continúe siendo compatible con el estado actual de Claims. "
    "Modificá, eliminá o atribuí cualquier afirmación que haya dejado de estar respaldada. "
    "Incorporá la información material nueva. "
    "Podés hacer cambios pequeños o reescribir por completo el artículo si el nuevo estado del Event lo requiere. "
    "current_article es la versión live (published_version), no el borrador. "
    "authoritative_claims es la verdad actual a comprobar; knowledge_delta resume qué cambió. "
    "No conserves una afirmación solo porque aparecía en la versión anterior. "
    "En body_blocks usá claim_refs C1/C2 del context, nunca UUIDs.\n"
)


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
                result = self._run(event, trigger=trigger, writing_run_id=str(run.id))
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

    def _run(self, event: Event, *, trigger: str, writing_run_id: str) -> dict:
        pipeline_runs = self.pipeline.list_for_event(event.id, limit=50)
        claim_run, verify_run = pair_from_runs(list(pipeline_runs))
        decisions = ((verify_run.metadata_json if verify_run is not None else None) or {}).get("decision_by_claim_id") or {}
        claims_snapshot = snapshot_claims(list(event.claims), decisions=decisions)
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
            previous_run = last_written_run(
                self.pipeline.list_for_event(event.id, limit=50)
            )
            if previous_run is not None:
                previous = (previous_run.metadata_json or {}).get("claims_snapshot") or []

        change = detect_material_change(previous, claims_snapshot)
        current_snap = (
            evidence_snapshot_for_version(pipeline_runs, article.current_version) if article is not None else None
        )
        unpaired_now_paired = (
            article is not None
            and article.published_version is not None
            and int(article.current_version) != int(article.published_version)
            and snapshot_lacks_usable_verification(current_snap)
            and claim_run is not None
            and verify_run is not None
        )
        skipped_now_complete = (
            article is not None
            and claim_run is not None
            and verify_run is not None
            and pair_completes_skipped_claims(current_snap, verify_run)
        )
        dropped_confirmation = confirmation_dropped(previous, claims_snapshot)
        published_gap = (
            article is not None
            and article.status == ArticleStatus.PUBLISHED
            and article.published_version is not None
            and int(article.current_version) == int(article.published_version)
            and live_coverage_gap(event)
        )
        if article is not None and not change.is_material:
            if unpaired_now_paired:
                base["material_reasons"] = list(change.reasons) + ["verification_now_paired"]
            elif skipped_now_complete:
                base["material_reasons"] = list(change.reasons) + ["verification_contract_completed"]
            elif dropped_confirmation:
                base["material_reasons"] = list(change.reasons) + ["confirmation_dropped"]
            elif published_gap:
                base["material_reasons"] = list(change.reasons) + ["coverage_gap_now_open"]
            elif has_unaudited_candidate(article, pipeline_runs):
                base["article_id"] = str(article.id)
                base["version"] = article.current_version
                base["written"] = True
                base["reason"] = "unaudited_candidate"
                base["material_reasons"] = change.reasons
                return base
            else:
                base["article_id"] = str(article.id)
                base["version"] = article.current_version
                base["reason"] = "no_material_change"
                base["material_reasons"] = change.reasons
                return base

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
        if claim_run is not None and verify_run is None:
            # A claim set without a SUCCESS verification of the same fingerprint
            # must not persist a candidate: Audit would only see contract_unpaired
            # / empty public_rendering. Tests without claim_resolution still write.
            base["reason"] = "verification_not_paired"
            base["stale_verification"] = True
            base["coverage_run_id"] = str(claim_run.id)
            base["claims_fingerprint"] = (claim_run.metadata_json or {}).get("claims_fingerprint")
            if article is not None:
                base["article_id"] = str(article.id)
                base["version"] = article.current_version
            return base
        evidence_snapshot = capture_evidence_snapshot(article_context, claim_run, verify_run)
        live = None
        if article is not None and article.published_version is not None:
            live = self.articles.get_version(article.id, article.published_version)
        prompt_context = article_context
        knowledge_delta = None
        if live is not None:
            published_snapshot = claims_snapshot_for_version(pipeline_runs, article.published_version) or previous
            knowledge_delta = build_knowledge_delta(published_snapshot, claims_snapshot, change)
            prompt_context = self._authoritative_context(
                event,
                article_context=article_context,
                live=live,
                delta=knowledge_delta,
                pipeline_runs=pipeline_runs,
            )
        llm = self.llm or get_structured_provider(ModelRole.WRITING)
        bind_model_role(ModelRole.WRITING.value, provider=self.settings.writing_provider)
        user_prompt = (
            self._update_user_prompt(live, knowledge_delta, prompt_context)
            if live is not None
            else self._user_prompt(prompt_context)
        )
        draft = llm.generate_structured(
            system_prompt=load_prompt("article_writing.md"),
            user_prompt=user_prompt,
            schema=ArticleDraft,
        )
        body, body_blocks = resolve_article_draft(
            draft, claim_ref_map=context_claim_ref_map(prompt_context)
        )
        if "verification_now_paired" in (base.get("material_reasons") or []):
            change_reason = "verification_now_paired"
        elif "verification_contract_completed" in (base.get("material_reasons") or []):
            change_reason = "verification_contract_completed"
        elif "confirmation_dropped" in (base.get("material_reasons") or []):
            change_reason = "confirmation_dropped"
        elif "coverage_gap_now_open" in (base.get("material_reasons") or []):
            change_reason = "coverage_gap_now_open"
        else:
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
            if article.status in {ArticleStatus.PUBLISHED, ArticleStatus.READY_FOR_REVIEW}:
                article.status = ArticleStatus.DRAFT
            self.session.flush()
        evidence_snapshot["version"] = article.current_version
        evidence_snapshot["writing_run_id"] = writing_run_id
        base.update(
            {
                "article_id": str(article.id),
                "created": created,
                "written": True,
                "reason": change_reason,
                "version": article.current_version,
                "writing_run_id": writing_run_id,
                "material_reasons": list(base.get("material_reasons") or change.reasons),
            }
        )
        if knowledge_delta is not None:
            base["knowledge_delta"] = knowledge_delta
            base["update"] = True
        claim_buckets = (
            prompt_context.confirmed_claims,
            prompt_context.single_source_claims,
            prompt_context.conflicting_claims,
            prompt_context.uncertain_claims,
            prompt_context.disproven_claims,
            prompt_context.outdated_claims,
        )
        base["claims_in_prompt"] = sum(len(bucket) for bucket in claim_buckets)
        base["source_context_count"] = len(prompt_context.source_contexts or [])
        base["source_contexts_included"] = bool(prompt_context.source_contexts)
        base.update(persist_snapshot_fields(evidence_snapshot))
        return base

    def _can_write(self, article) -> bool:
        if article.status in {ArticleStatus.DRAFT, ArticleStatus.READY_FOR_REVIEW}:
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
                "Claims SINGLE_SOURCE o UNCERTAIN: pueden incluirse, pero no los escribas como "
                "hecho categórico de Sin Línea. En titular, bajada y primer párrafo la atribución "
                "o el lenguaje epistémico es obligatorio. Combinar dos SINGLE_SOURCE no autoriza "
                "una síntesis categórica ni eleva la certeza.\n"
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

    def _authoritative_context(self, event: Event, *, article_context, live, delta: dict, pipeline_runs):
        wanted = set(claim_ids_in_body_blocks(live.body_blocks))
        for row in delta.get("new_claims") or []:
            if row.get("id"):
                wanted.add(str(row["id"]))
        for collection in (
            delta.get("changed_claims"),
            delta.get("new_conflicts"),
            delta.get("resolved_conflicts"),
            delta.get("outdated_or_disproven_claims"),
        ):
            for row in collection or []:
                claim_id = row.get("id") or (row.get("after") or {}).get("id")
                if claim_id:
                    wanted.add(str(claim_id))
        groups: dict[str, list[Claim]] = {}
        by_id = {str(claim.id): claim for claim in event.claims}
        for claim in event.claims:
            groups.setdefault(comparison_key_for(claim), []).append(claim)
        extra: set[str] = set()
        for claim_id in list(wanted):
            claim = by_id.get(claim_id)
            if claim is None:
                continue
            for member in groups.get(comparison_key_for(claim), []):
                extra.add(str(member.id))
            for bucket in (
                article_context.confirmed_claims,
                article_context.single_source_claims,
                article_context.conflicting_claims,
                article_context.uncertain_claims,
                article_context.disproven_claims,
                article_context.outdated_claims,
            ):
                for ctx_claim in bucket:
                    if ctx_claim.id == claim_id:
                        extra.update(str(item) for item in ctx_claim.related_claim_ids)
        wanted.update(extra)
        return build_article_context(
            event,
            entities=self.entities.list_for_event(event.id),
            pipeline_runs=pipeline_runs,
            max_claims=max(len(wanted), 1),
            max_sources=self.settings.max_writing_sources_per_event,
            excerpt_chars=self.settings.writing_excerpt_chars,
            max_source_contexts=0,
            source_context_chars=self.settings.writing_source_context_chars,
            claim_ids=wanted or None,
            include_source_contexts=False,
        )

    def _update_user_prompt(self, live, knowledge_delta: dict, article_context) -> str:
        payload = {
            "current_article": {
                "version_number": live.version_number,
                "headline": live.headline,
                "summary": live.summary,
                "body": live.body,
            },
            "knowledge_delta": knowledge_delta,
            "authoritative_claims": json.loads(article_context.model_dump_json()),
        }
        return _UPDATE_INSTRUCTIONS + json.dumps(payload, ensure_ascii=False)


def has_unaudited_candidate(article: Article, runs: list[PipelineRun]) -> bool:
    if article.published_version is None:
        return False
    if int(article.current_version) == int(article.published_version):
        return False
    has_writing = False
    for run in runs:
        if run.stage != WRITING_STAGE or run.status != PipelineStatus.SUCCESS:
            continue
        meta = run.metadata_json or {}
        bound = meta.get("version")
        if bound is None or int(bound) != int(article.current_version):
            continue
        has_writing = True
        break
    if not has_writing:
        return False
    for run in runs:
        if run.stage != AUDITING_STAGE or run.status != PipelineStatus.SUCCESS:
            continue
        meta = run.metadata_json or {}
        if meta.get("passed") is not True:
            continue
        version_after = meta.get("version_after")
        if version_after is not None and int(version_after) == int(article.current_version):
            return False
    return True


def should_enqueue_write(session: Session, event_id: UUID) -> bool:
    try:
        articles = ArticleRepository(session)
        article = articles.get_by_event_id(event_id)
        if article is None:
            return True
        pipeline = PipelineRunRepository(session)
        runs = pipeline.list_for_event(event_id, limit=50)
        _claim_run, verify_run = pair_from_runs(list(runs))
        current_snap = (
            evidence_snapshot_for_version(runs, article.current_version) if article is not None else None
        )
        if pair_completes_skipped_claims(current_snap, verify_run):
            return True
        if has_unaudited_candidate(article, runs):
            return True
        stmt = (
            select(Event)
            .options(selectinload(Event.claims))
            .where(Event.id == event_id)
        )
        event = session.scalars(stmt).first()
        if event is None:
            return True
        claims = list(event.claims)
        previous_run = last_written_run(runs)
        previous = ((previous_run.metadata_json if previous_run is not None else None) or {}).get("claims_snapshot")
        decisions = ((verify_run.metadata_json if verify_run is not None else None) or {}).get("decision_by_claim_id") or {}
        current = snapshot_claims(claims, decisions=decisions)
        if detect_material_change(previous, current).is_material:
            return True
        if confirmation_dropped(previous, current):
            return True
        if (
            article.status == ArticleStatus.PUBLISHED
            and article.published_version is not None
            and int(article.current_version) == int(article.published_version)
            and live_coverage_gap(event)
        ):
            return True
        return False
    except Exception:
        return True
