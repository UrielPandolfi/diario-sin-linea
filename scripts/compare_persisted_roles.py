"""Compara extracción, relevancia y planificación sobre casos ya persistidos.

No busca ni publica. Las llamadas nuevas usan el resto del tope de USD 3.
Los textos de las notas no se escriben en el informe.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

for line in Path(r"E:\Diario Sin Línea\.env").read_text(encoding="utf-8").splitlines():
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    os.environ[key.strip()] = value.strip().strip('"')

os.environ["DATABASE_URL"] = "postgresql+psycopg://sin_linea:sin_linea@127.0.0.1:55432/sin_linea_costos"
os.environ["REDIS_URL"] = "redis://127.0.0.1:6380/2"
os.environ["AUTO_PUBLISH"] = "false"
os.environ["ARTICLE_IMAGE_ENABLED"] = "false"
os.environ["SEARCH_CACHE_ENABLED"] = "false"
os.environ["VERIFICATION_REUSE_ENABLED"] = "false"
os.environ["COST_PROFILE"] = "current"
os.environ["USAGE_ENVIRONMENT"] = "experiment"
os.environ["JOB_MAX_RETRIES"] = "1"

from sqlalchemy import func, select, text
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.prompts import load_prompt
from app.core.usage_context import usage_scope
from app.domain.enums import ClaimImportance, ClaimStatus
from app.models.claim import Claim
from app.models.event import Event
from app.models.llm_usage import LlmUsage
from app.models.pipeline import PipelineRun
from app.models.source import SourceItem
from app.providers.base import SearchHit
from app.providers.openai_provider import OpenAIStructuredProvider
from app.schemas.detection import EventCandidate
from app.schemas.research import RelevanceBatch
from app.schemas.verification import VerificationPlan
from app.services.call_budget import CallBudgetExceeded, install_budget
from app.services.editorial_gate import evaluate_editorial_gate, needs_location_fallback
from app.services.research_service import ResearchService, hit_conflicts_with_event
from app.services.verification_plan import heuristic_plan, refine_plan
from app.services.verification_service import VerificationService

BUDGET_CAP = Decimal("3")
POLL = (
    "e6c037d3-7ef3-4bd9-9765-d205fac1a2b3",
    "1c28e01f-33cf-4ac1-bc9d-6bc3fce79dd8",
)
HIST_SOURCES = Path(r"E:\temp\sinlinea_hist_sources.json")
HIST_PLANS = Path(r"E:\temp\sinlinea_hist_plans.json")
HIST_POLICY = Path(r"E:\temp\sinlinea_policy_hist.json")
OUT = Path(r"E:\temp\sinlinea_role_compare.json")


def _provider(name: str, model: str) -> OpenAIStructuredProvider:
    settings = get_settings()
    if name == "deepseek":
        return OpenAIStructuredProvider(
            api_key=settings.deepseek_api_key or "",
            model=model,
            base_url="https://api.deepseek.com",
            provider_name="deepseek",
            thinking="disabled",
        )
    return OpenAIStructuredProvider(
        api_key=settings.openai_api_key or "",
        model=model,
        provider_name="openai",
    )


def _spent(session) -> Decimal:
    total = session.scalar(select(func.coalesce(func.sum(LlmUsage.estimated_cost_usd), 0)))
    return Decimal(total)


def _call(stage: str, event_id: str | None, role: str, provider, system: str, user: str, schema):
    with usage_scope(
        stage=stage,
        event_id=UUID(event_id) if event_id else None,
        model_role=role,
        provider=provider.provider_name,
    ):
        try:
            return provider.generate_structured(system_prompt=system, user_prompt=user, schema=schema), None
        except CallBudgetExceeded as exc:
            return None, f"budget:{exc}"
        except Exception as exc:
            return None, f"{type(exc).__name__}:{exc}"[:400]


def _plan_view(plan: VerificationPlan | dict) -> dict:
    if isinstance(plan, dict):
        plan = VerificationPlan.model_validate(plan)
    return {
        "target": plan.verification_target.value,
        "temporal_scope": plan.temporal_scope.value,
        "subject": plan.subject.value,
        "forum": plan.judicial_forum.value,
        "primary": plan.primary_source_required,
        "corroboration": plan.independent_corroboration_required,
        "year_hint": plan.year_hint,
    }


def _same_plan(left: dict, right: dict) -> bool:
    keys = ("target", "temporal_scope", "subject", "forum", "primary", "corroboration")
    return all(left.get(key) == right.get(key) for key in keys)


def _detached_claim(text_value: str, claim_type: str) -> Claim:
    return Claim(
        id=uuid4(),
        event_id=uuid4(),
        canonical_text=text_value,
        claim_type=claim_type or "unknown",
        importance=ClaimImportance.MEDIUM,
        status=ClaimStatus.UNCERTAIN,
    )


def _parse_prompt(prompt: str) -> tuple[str, str]:
    claim_type = "unknown"
    text_value = ""
    for line in prompt.splitlines():
        if line.startswith("canonical_text="):
            text_value = line.split("=", 1)[1]
        elif line.startswith("claim_type="):
            claim_type = line.split("=", 1)[1].strip()
    return text_value, claim_type


def _extraction_view(candidate: EventCandidate, source_text: str) -> dict:
    gate = evaluate_editorial_gate(candidate, source_text=source_text)
    return {
        "event_type": candidate.event_type,
        "locality": candidate.locality,
        "province": candidate.province,
        "country_code": candidate.country_code,
        "scope": candidate.editorial_scope.value,
        "topic": candidate.editorial_topic.value,
        "public_affairs": candidate.is_public_affairs,
        "gate_allowed": gate.allowed,
        "gate_reason": gate.reason.value if gate.reason else None,
        "location_fallback": needs_location_fallback(candidate),
        "what_happened": (candidate.what_happened or "")[:180],
    }


def main() -> None:
    get_settings.cache_clear()
    session = SessionLocal()
    try:
        dbname = session.execute(text("select current_database()")).scalar_one()
        if dbname != "sin_linea_costos":
            raise SystemExit(f"base inesperada: {dbname}")
        spent = _spent(session)
        remaining = BUDGET_CAP - spent
        install_budget(remaining)
        settings = get_settings()
        nano = _provider("openai", settings.ultra_light_processing_model or "gpt-5-nano")
        flash = _provider("deepseek", "deepseek-flash")
        extract_system = load_prompt("event_extraction.md")
        plan_system = load_prompt("verification_plan.md")
        relevance_system = load_prompt("research_relevance.md")
        report: dict = {
            "database": dbname,
            "spent_before": str(spent),
            "remaining_before": str(remaining),
            "extraction": [],
            "plans": [],
            "relevance": [],
            "limits": [
                "La relevancia se rehace solo sobre documentos ya guardados. Los resultados de búsqueda no adjuntados no se persistieron.",
                "El fragmento usado es el inicio del texto guardado, no el snippet original del buscador.",
                "Las consultas de investigación del poll salieron del código, no de un modelo.",
            ],
        }

        def extract(event_id: str | None, model_name: str, provider, item: dict, stored: dict) -> None:
            user = (
                f"Título: {item.get('title') or ''}\n"
                f"URL: {item.get('url') or ''}\n"
                f"Publicado: {item.get('published_at') or ''}\n\n"
                f"{(item.get('text') or '')[:8000]}"
            )
            result, error = _call("replay_extraction", event_id, "ultra_light", provider, extract_system, user, EventCandidate)
            row = {"event_id": event_id, "model": model_name, "stored": stored, "error": error}
            if result is not None:
                row["executed"] = _extraction_view(result, item.get("text") or "")
            report["extraction"].append(row)

        for eid in POLL:
            event = session.scalars(
                select(Event).where(Event.id == eid).options(selectinload(Event.event_sources), selectinload(Event.claims))
            ).one()
            primary = next(link for link in event.event_sources if link.is_primary)
            item = session.get(SourceItem, primary.source_item_id)
            body = item.clean_text or item.raw_text or ""
            extract(
                eid,
                nano.model,
                nano,
                {"title": item.title, "url": item.url, "published_at": str(item.published_at or ""), "text": body},
                {
                    "model": "deepseek-flash",
                    "event_type": event.event_type,
                    "locality": event.locality,
                    "province": event.province,
                    "gate_allowed": True,
                    "title": (event.title_internal or "")[:180],
                },
            )
            service = VerificationService(session)
            research = ResearchService(session)
            run = session.scalars(
                select(PipelineRun)
                .where(PipelineRun.event_id == event.id, PipelineRun.stage == "verification")
                .order_by(PipelineRun.finished_at.desc())
            ).first()
            plans = ((run.metadata_json if run else None) or {}).get("plans") or {}
            for claim in event.claims:
                stored_plan = plans.get(str(claim.id))
                if not isinstance(stored_plan, dict):
                    continue
                prompt = service._plan_prompt(event, claim)
                result, error = _call(
                    "replay_plan", eid, "ultra_light", nano, plan_system, prompt, VerificationPlan
                )
                row = {
                    "event_id": eid,
                    "claim_id": str(claim.id),
                    "model": nano.model,
                    "stored_model": "deepseek-flash",
                    "stored": _plan_view(stored_plan),
                    "error": error,
                }
                if result is not None:
                    refined = refine_plan(result, heuristic_plan(claim), claim=claim)
                    row["executed"] = _plan_view(refined)
                    row["same_decisions"] = _same_plan(row["stored"], row["executed"])
                report["plans"].append(row)
            hits = []
            for link in event.event_sources:
                if link.is_primary:
                    continue
                source = session.get(SourceItem, link.source_item_id)
                text_body = source.clean_text or source.raw_text or ""
                hits.append(SearchHit(title=source.title or "", url=source.url, snippet=text_body[:400]))
            user = research._relevance_prompt(event, hits)
            result, error = _call(
                "replay_relevance", eid, "ultra_light", nano, relevance_system, user, RelevanceBatch
            )
            report["relevance"].append(_relevance_row(eid, nano.model, "deepseek-flash", event, hits, result, error))

        hist_sources = json.loads(HIST_SOURCES.read_text(encoding="utf-8"))
        hist_plans = {row["event_id"]: row["plans"] for row in json.loads(HIST_PLANS.read_text(encoding="utf-8"))}
        hist_policy = json.loads(HIST_POLICY.read_text(encoding="utf-8"))
        prompts = {}
        for event in hist_policy["events"]:
            for claim in event["claims"]:
                prompts[claim["claim_id"]] = claim.get("plan_prompt") or ""
        for event_row in hist_sources:
            primary = next(src for src in event_row["sources"] if src["primary"])
            extract(
                None,
                flash.model,
                flash,
                primary,
                {
                    "model": "gpt-5-nano",
                    "event_id": event_row["event_id"],
                    "event_type": event_row["event_type"],
                    "locality": event_row["locality"],
                    "province": event_row["province"],
                    "gate_allowed": True,
                    "title": (event_row["title"] or "")[:180],
                },
            )
            detached = Event(
                id=UUID(event_row["event_id"]),
                title_internal=event_row["title"],
                event_type=event_row["event_type"],
                locality=event_row["locality"],
                province=event_row["province"],
                detected_at=datetime.fromisoformat(event_row["detected_at"]),
            )
            hits = [
                SearchHit(title=src["title"], url=src["url"], snippet=(src.get("snippet") or "")[:400])
                for src in event_row["sources"]
                if not src["primary"]
            ]
            user = ResearchService(session)._relevance_prompt(detached, hits)
            result, error = _call(
                "replay_relevance", None, "ultra_light", flash, relevance_system, user, RelevanceBatch
            )
            report["relevance"].append(
                _relevance_row(event_row["event_id"], flash.model, "gpt-5-nano", detached, hits, result, error)
            )
            for claim_id, stored_plan in (hist_plans.get(event_row["event_id"]) or {}).items():
                prompt = prompts.get(claim_id) or ""
                if not prompt or not isinstance(stored_plan, dict):
                    report["plans"].append({"claim_id": claim_id, "error": "sin prompt guardado"})
                    continue
                text_value, claim_type = _parse_prompt(prompt)
                claim = _detached_claim(text_value, claim_type)
                result, error = _call(
                    "replay_plan", None, "ultra_light", flash, plan_system, prompt, VerificationPlan
                )
                row = {
                    "event_id": event_row["event_id"],
                    "claim_id": claim_id,
                    "model": flash.model,
                    "stored_model": "gpt-5-nano",
                    "stored": _plan_view(stored_plan),
                    "error": error,
                }
                if result is not None:
                    refined = refine_plan(result, heuristic_plan(claim), claim=claim)
                    row["executed"] = _plan_view(refined)
                    row["same_decisions"] = _same_plan(row["stored"], row["executed"])
                report["plans"].append(row)

        session.commit()
        report["spent_after"] = str(_spent(session))
        OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print("spent", report["spent_before"], "->", report["spent_after"], "bytes", OUT.stat().st_size)
    finally:
        session.close()


def _relevance_row(event_id, model, stored_model, event, hits, result, error) -> dict:
    rows = []
    if result is not None:
        by_url = {hit.url: hit for hit in hits}
        for item in result.hits:
            search_hit = by_url.get(item.url)
            classification = item.classification.value
            demoted = False
            if (
                search_hit is not None
                and item.classification.value == "SAME_EVENT"
                and hit_conflicts_with_event(event, search_hit)
            ):
                classification = "DIFFERENT_EVENT"
                demoted = True
            host = re.sub(r"^www\.", "", (item.url.split("/")[2] if "://" in item.url else item.url))
            rows.append({"host": host, "classification": classification, "demoted": demoted})
    kept = sum(1 for row in rows if row["classification"] == "SAME_EVENT")
    return {
        "event_id": event_id,
        "model": model,
        "stored_model": stored_model,
        "stored_kept_documents": len(hits),
        "executed_same_event": kept,
        "executed_other": len(rows) - kept,
        "error": error,
        "rows": rows,
    }


if __name__ == "__main__":
    main()
