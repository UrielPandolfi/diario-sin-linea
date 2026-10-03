"""Rejuega assessment, juicio y auditoría con los prompts reales.

No busca, no publica y no reescribe artículos. El tope es el resto de los USD 3
ya consumidos en esta base aislada. Si la reserva no entra, la llamada no se hace.
"""

from __future__ import annotations

import json
import os
import sys
from decimal import Decimal
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

ENV = Path(r"E:\Diario Sin Línea\.env")
for line in ENV.read_text(encoding="utf-8").splitlines():
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
from app.models.article import Article, ArticleVersion
from app.models.event import Event
from app.models.llm_usage import LlmUsage
from app.models.pipeline import PipelineRun
from app.schemas.auditing import ArticleAuditResult
from app.schemas.verification import CheapClaimEvidenceAssessment, VerificationPlan, VerificationResult
from app.services.audit_service import AuditService
from app.services.call_budget import CallBudgetExceeded, install_budget
from app.services.evidence_snapshot import article_context_from_snapshot, evidence_snapshot_for_version
from app.services.verification_service import VerificationService, _PacketSource
from app.providers.openai_provider import OpenAIStructuredProvider

BUDGET_CAP = Decimal("3")
POLL_EVENTS = (
    "e6c037d3-7ef3-4bd9-9765-d205fac1a2b3",
    "1c28e01f-33cf-4ac1-bc9d-6bc3fce79dd8",
)
HIST_VERIFY = Path(r"E:\temp\sinlinea_hist_verify.json")
HIST_AUDIT = Path(r"E:\temp\sinlinea_hist_prompts.json")
REPORT = ROOT / "scripts" / "real_role_report.json"


def _provider(name: str, model: str, *, thinking: str | None = None) -> OpenAIStructuredProvider:
    settings = get_settings()
    if name == "deepseek":
        return OpenAIStructuredProvider(
            api_key=settings.deepseek_api_key or "",
            model=model,
            base_url="https://api.deepseek.com",
            provider_name="deepseek",
            thinking=thinking or "disabled",
        )
    return OpenAIStructuredProvider(
        api_key=settings.openai_api_key or "",
        model=model,
        provider_name="openai",
    )


def _norm(value: str | None) -> str:
    return " ".join((value or "").split()).casefold()


def _in_prompt(excerpt: str | None, prompt: str) -> bool:
    needle = _norm(excerpt)
    return len(needle) >= 20 and needle in _norm(prompt)


def _compact_assessment(result: CheapClaimEvidenceAssessment, claim_text: str, prompt: str) -> dict:
    rows = []
    for row in result.judgements:
        excerpt = row.excerpt or ""
        rows.append(
            {
                "relation": row.relation.value,
                "source_ref": row.source_ref,
                "excerpt_equals_claim": _norm(excerpt) == _norm(claim_text),
                "excerpt_in_prompt": _in_prompt(excerpt, prompt),
                "excerpt": excerpt[:240],
            }
        )
    return {"ambiguous": result.ambiguous, "reason": (result.reason or "")[:300], "judgements": rows}


def _compact_sol(result: VerificationResult, claim_text: str, prompt: str) -> dict:
    evidence = []
    for row in result.evidence:
        excerpt = row.excerpt or ""
        evidence.append(
            {
                "source_ref": row.source_ref,
                "evidence_type": row.evidence_type.value,
                "excerpt_equals_claim": _norm(excerpt) == _norm(claim_text),
                "excerpt_in_prompt": _in_prompt(excerpt, prompt),
                "excerpt": excerpt[:240],
            }
        )
    return {
        "status": result.status.value,
        "confidence": result.confidence,
        "reason": (result.reason or "")[:400],
        "evidence": evidence,
    }


def _compact_audit(result: ArticleAuditResult) -> dict:
    issues = []
    for issue in result.issues:
        issues.append(
            {
                "severity": issue.severity.value,
                "type": issue.type.value,
                "reason": issue.reason.value if issue.reason else None,
                "text": (issue.text or "")[:180],
                "explanation": (issue.explanation or "")[:300],
            }
        )
    blocking = [row for row in issues if row["severity"] in {"HIGH", "MEDIUM"}]
    return {"passed": result.passed, "blocking": blocking, "issues": issues}


def _call(stage: str, event_id: str | None, role: str, provider, system: str, user: str, schema):
    with usage_scope(stage=stage, event_id=UUID(event_id) if event_id else None, model_role=role, provider=provider.provider_name):
        try:
            return provider.generate_structured(system_prompt=system, user_prompt=user, schema=schema), None
        except CallBudgetExceeded as exc:
            return None, f"budget:{exc}"
        except Exception as exc:
            return None, f"{type(exc).__name__}:{exc}"[:500]


def _spent(session) -> tuple[Decimal, int]:
    total, unknown = session.execute(
        select(
            func.coalesce(func.sum(LlmUsage.estimated_cost_usd), 0),
            func.count().filter(LlmUsage.estimated_cost_usd.is_(None)),
        )
    ).one()
    return Decimal(total), int(unknown)


def main() -> None:
    get_settings.cache_clear()
    session = SessionLocal()
    try:
        dbname = session.execute(text("select current_database()")).scalar_one()
        if dbname != "sin_linea_costos":
            raise SystemExit(f"base inesperada: {dbname}")
        spent, unknown = _spent(session)
        remaining = BUDGET_CAP - spent
        if remaining <= 0:
            raise SystemExit(f"sin resto de presupuesto: {spent}")
        install_budget(remaining)
        settings = get_settings()
        nano = _provider("openai", settings.ultra_light_processing_model or "gpt-5-nano")
        gpt4o = _provider("openai", settings.verification_model or "gpt-4o")
        audit_current = _provider("openai", settings.auditing_model or "gpt-4o")
        flash = _provider("deepseek", "deepseek-flash", thinking="disabled")
        pro = _provider("deepseek", "deepseek-v4-pro", thinking="disabled")
        assess_system = load_prompt("claim_evidence_assessment.md")
        sol_system = load_prompt("verification.md")
        audit_system = load_prompt("article_audit.md")
        report: dict = {
            "database": dbname,
            "spent_before": str(spent),
            "unknown_before": unknown,
            "remaining_before": str(remaining),
            "models": {
                "current_assessor": nano.model,
                "current_verification": gpt4o.model,
                "current_audit": audit_current.model,
                "candidate_assessor": flash.model,
                "candidate_verification": pro.model,
                "candidate_audit": flash.model,
            },
            "assessments": [],
            "judgements": [],
            "audits": [],
            "skipped": [],
        }

        hist = json.loads(HIST_VERIFY.read_text(encoding="utf-8"))
        decisions = {}
        for row in json.loads(HIST_AUDIT.read_text(encoding="utf-8")):
            latest = (row.get("verifications") or [None])[0] or {}
            decisions[row["event_id"]] = latest.get("decision_status") or {}

        for event in hist:
            for claim in event["claims"]:
                prompt = claim["prompt"]
                result, error = _call(
                    "replay_assessment",
                    event["event_id"],
                    "ultra_light_processing",
                    flash,
                    assess_system,
                    prompt,
                    CheapClaimEvidenceAssessment,
                )
                if error:
                    report["skipped"].append({"role": "assessment", "claim_id": claim["claim_id"], "error": error})
                    if error.startswith("budget:"):
                        _finish(session, report)
                        return
                    continue
                report["assessments"].append(
                    {
                        "corpus": "historical",
                        "event_id": event["event_id"],
                        "claim_id": claim["claim_id"],
                        "claim": claim["canonical_text"][:220],
                        "persisted_profile": "current",
                        "persisted_model": "gpt-5-nano",
                        "executed_profile": "candidate",
                        "executed_model": "deepseek-flash",
                        "escalated_originally": claim["escalated"],
                        "policy_status": (decisions.get(event["event_id"]) or {}).get(claim["claim_id"]),
                        "persisted": {
                            "judgements": claim["judgements"],
                            "ambiguous": claim["ambiguous"],
                        },
                        "executed": _compact_assessment(result, claim["canonical_text"], prompt),
                    }
                )
                if not claim["escalated"]:
                    continue
                sol, error = _call(
                    "replay_verification",
                    event["event_id"],
                    "verification",
                    pro,
                    sol_system,
                    prompt,
                    VerificationResult,
                )
                if error:
                    report["skipped"].append({"role": "verification", "claim_id": claim["claim_id"], "error": error})
                    if error.startswith("budget:"):
                        _finish(session, report)
                        return
                    continue
                report["judgements"].append(
                    {
                        "corpus": "historical",
                        "event_id": event["event_id"],
                        "claim_id": claim["claim_id"],
                        "claim": claim["canonical_text"][:220],
                        "persisted_profile": "current",
                        "persisted_model": "gpt-4o",
                        "executed_profile": "candidate",
                        "executed_model": "deepseek-v4-pro",
                        "policy_status": (decisions.get(event["event_id"]) or {}).get(claim["claim_id"]),
                        "persisted": claim["model_result"],
                        "executed": _compact_sol(sol, claim["canonical_text"], prompt),
                    }
                )

        service = VerificationService(session)
        auditor = AuditService(session)
        for event_id in POLL_EVENTS:
            event = session.scalars(
                select(Event).where(Event.id == event_id).options(selectinload(Event.claims))
            ).one()
            claims = {str(row.id): row for row in event.claims}
            run = session.scalars(
                select(PipelineRun)
                .where(PipelineRun.event_id == event.id, PipelineRun.stage == "verification")
                .order_by(PipelineRun.finished_at.desc())
            ).first()
            meta = (run.metadata_json if run else None) or {}
            for cid, packet in (meta.get("packets") or {}).items():
                claim = claims.get(cid)
                if claim is None:
                    continue
                sources = [
                    _PacketSource(
                        ref=int(src.get("source_ref") or 0),
                        url=src.get("url") or "",
                        title=src.get("title") or "",
                        snippet=src.get("snippet") or "",
                        body_source=src.get("body_source") or "",
                    )
                    for src in packet
                ]
                plan_raw = (meta.get("plans") or {}).get(cid)
                plan = VerificationPlan.model_validate(plan_raw) if isinstance(plan_raw, dict) else None
                prompt = service._user_prompt(event, claim, sources, plan)
                stored = (meta.get("assessments") or {}).get(cid) or {}
                stored_rows = []
                for row in stored.get("judgements") or []:
                    if not isinstance(row, dict):
                        continue
                    excerpt = row.get("excerpt") or ""
                    stored_rows.append(
                        {
                            "relation": row.get("relation"),
                            "source_ref": row.get("source_ref"),
                            "excerpt_equals_claim": _norm(excerpt) == _norm(claim.canonical_text),
                            "excerpt_in_prompt": _in_prompt(excerpt, prompt),
                            "excerpt": excerpt[:240],
                        }
                    )
                result, error = _call(
                    "replay_assessment",
                    event_id,
                    "ultra_light_processing",
                    nano,
                    assess_system,
                    prompt,
                    CheapClaimEvidenceAssessment,
                )
                if error:
                    report["skipped"].append({"role": "assessment", "claim_id": cid, "error": error})
                    if error.startswith("budget:"):
                        _finish(session, report)
                        return
                else:
                    report["assessments"].append(
                        {
                            "corpus": "poll",
                            "event_id": event_id,
                            "claim_id": cid,
                            "claim": (claim.canonical_text or "")[:220],
                            "persisted_profile": "candidate",
                            "persisted_model": "deepseek-flash",
                            "executed_profile": "current",
                            "executed_model": nano.model,
                            "escalated_originally": bool((meta.get("escalated") or {}).get(cid)),
                            "policy_status": ((meta.get("decision_by_claim_id") or {}).get(cid) or {}).get("status"),
                            "persisted": {"judgements": stored_rows, "ambiguous": stored.get("ambiguous")},
                            "executed": _compact_assessment(result, claim.canonical_text or "", prompt),
                        }
                    )
                if not (meta.get("escalated") or {}).get(cid):
                    continue
                stored_sol = (meta.get("model_results") or {}).get(cid)
                sol, error = _call(
                    "replay_verification",
                    event_id,
                    "verification",
                    gpt4o,
                    sol_system,
                    prompt,
                    VerificationResult,
                )
                if error:
                    report["skipped"].append({"role": "verification", "claim_id": cid, "error": error})
                    if error.startswith("budget:"):
                        _finish(session, report)
                        return
                    continue
                report["judgements"].append(
                    {
                        "corpus": "poll",
                        "event_id": event_id,
                        "claim_id": cid,
                        "claim": (claim.canonical_text or "")[:220],
                        "persisted_profile": "candidate",
                        "persisted_model": "deepseek-v4-pro",
                        "executed_profile": "current",
                        "executed_model": gpt4o.model,
                        "policy_status": ((meta.get("decision_by_claim_id") or {}).get(cid) or {}).get("status"),
                        "persisted": stored_sol,
                        "executed": _compact_sol(sol, claim.canonical_text or "", prompt),
                    }
                )

            article = session.scalars(select(Article).where(Article.event_id == event.id)).first()
            runs = list(
                session.scalars(
                    select(PipelineRun).where(PipelineRun.event_id == event.id).order_by(PipelineRun.started_at.asc())
                )
            )
            versions = {
                row.version_number: row
                for row in session.scalars(select(ArticleVersion).where(ArticleVersion.article_id == article.id))
            } if article is not None else {}
            seen = set()
            for run in runs:
                if run.stage != "auditing":
                    continue
                meta = run.metadata_json or {}
                version_no = meta.get("version_before") or (article.current_version if article else None)
                if version_no in seen or article is None:
                    continue
                seen.add(version_no)
                version = versions.get(version_no)
                viewed = article
                if version is not None and version.version_number != article.current_version:
                    viewed = type("ArticleView", (), {})()
                    viewed.headline = version.headline
                    viewed.summary = version.summary
                    viewed.body = version.body
                    viewed.body_blocks = version.body_blocks
                    viewed.published_version = article.published_version
                snapshot = evidence_snapshot_for_version(runs, version_no)
                context = article_context_from_snapshot(snapshot) if snapshot else None
                prompt = auditor._audit_user_prompt(viewed, context, snapshot)
                result, error = _call(
                    "replay_audit",
                    event_id,
                    "auditing",
                    audit_current,
                    audit_system,
                    prompt,
                    ArticleAuditResult,
                )
                if error:
                    report["skipped"].append({"role": "audit", "event_id": event_id, "version": version_no, "error": error})
                    if error.startswith("budget:"):
                        _finish(session, report)
                        return
                    continue
                report["audits"].append(
                    {
                        "corpus": "poll",
                        "event_id": event_id,
                        "version": version_no,
                        "headline": viewed.headline,
                        "persisted_profile": "candidate",
                        "persisted_model": "deepseek-flash",
                        "persisted_passed": meta.get("passed"),
                        "persisted_reason": meta.get("reason"),
                        "executed_profile": "current",
                        "executed_model": audit_current.model,
                        "executed": _compact_audit(result),
                    }
                )

        for row in json.loads(HIST_AUDIT.read_text(encoding="utf-8")):
            prompt = row.get("audit_prompt")
            if not prompt:
                continue
            result, error = _call(
                "replay_audit",
                row["event_id"],
                "auditing",
                flash,
                audit_system,
                prompt,
                ArticleAuditResult,
            )
            stored = (row.get("audits") or [None])[0]
            if error:
                report["skipped"].append({"role": "audit", "event_id": row["event_id"], "error": error})
                if error.startswith("budget:"):
                    break
                continue
            report["audits"].append(
                {
                    "corpus": "historical",
                    "event_id": row["event_id"],
                    "headline": (row.get("article") or {}).get("headline"),
                    "persisted_profile": "current",
                    "persisted_model": "gpt-4o",
                    "persisted_passed": None if stored is None else stored.get("passed"),
                    "persisted_reason": None if stored is None else stored.get("reason"),
                    "executed_profile": "candidate",
                    "executed_model": "deepseek-flash",
                    "executed": _compact_audit(result),
                }
            )
        _finish(session, report)
    finally:
        session.close()


def _finish(session, report: dict) -> None:
    session.expire_all()
    spent, unknown = _spent(session)
    report["spent_after"] = str(spent)
    report["unknown_after"] = unknown
    report["replay_delta"] = str(Decimal(report["spent_after"]) - Decimal(report["spent_before"]))
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        "delta",
        report["replay_delta"],
        "after",
        report["spent_after"],
        "assess",
        len(report["assessments"]),
        "sol",
        len(report["judgements"]),
        "audit",
        len(report["audits"]),
        "skipped",
        len(report["skipped"]),
    )


if __name__ == "__main__":
    main()
