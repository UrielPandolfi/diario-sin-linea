"""Aplica la política de verificación a juicios ya guardados y revierte la sesión.

No llama modelos ni hace commit. La evidencia original queda como estaba.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

for line in Path(r"E:\Diario Sin Línea\.env").read_text(encoding="utf-8").splitlines():
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    os.environ[key.strip()] = value.strip().strip('"')

if len(sys.argv) > 1 and sys.argv[1] == "sin_linea_costos":
    os.environ["DATABASE_URL"] = (
        "postgresql+psycopg://sin_linea:sin_linea@127.0.0.1:55432/sin_linea_costos"
    )
os.environ["AUTO_PUBLISH"] = "false"
os.environ["ARTICLE_IMAGE_ENABLED"] = "false"
os.environ["COST_PROFILE"] = "current"

from sqlalchemy import func, select, text
from sqlalchemy.orm import selectinload

from app.core.db import SessionLocal
from app.core.urls import canonicalize_url
from app.domain.enums import EvidenceType
from app.models.claim import Claim
from app.models.event import Event
from app.models.pipeline import PipelineRun
from app.models.source import SourceItem
from app.schemas.verification import CheapClaimEvidenceAssessment, VerificationPlan, VerificationResult
from app.services.evidence_source_registry import preferred_domains
from app.services.information_origin import assess_origins
from app.services.verification_plan import assessment_has_support, needs_sol_after_assessment
from app.services.verification_service import VerificationService, _PacketSource

PRIORITY = ("84d4352c", "fb6ac81f", "55ca7750")


def _fingerprint(claim: Claim) -> list[tuple]:
    return sorted(
        (
            str(row.id),
            str(row.source_item_id),
            row.evidence_type.value,
            row.excerpt or "",
        )
        for row in claim.evidence
    )


def _origins(claim: Claim, packet_size: int) -> dict:
    found = assess_origins(claim, packet_size=packet_size)
    return {
        "known_independent": found.known_independent,
        "unknown_groups": found.unknown_groups,
        "reporting_independent": found.reporting_independent,
        "authoritative_independent": found.authoritative_independent,
        "reprint_collapsed": found.reprint_collapsed,
        "documents_supporting": found.documents_supporting,
        "information_origins": list(found.information_origins),
        "statement_evidence_class": (
            found.statement_evidence_class.value if found.statement_evidence_class else None
        ),
    }


def _item_for(session, url: str) -> SourceItem | None:
    canonical = canonicalize_url(url) or url
    return session.scalars(
        select(SourceItem).where(
            (SourceItem.url == url)
            | (SourceItem.canonical_url == url)
            | (SourceItem.canonical_url == canonical)
            | (SourceItem.url == canonical)
        )
    ).first()


def _packet(session, packet_json: list) -> list[_PacketSource]:
    sources = []
    for src in packet_json or []:
        url = src.get("url") or ""
        sources.append(
            _PacketSource(
                ref=int(src.get("source_ref") or 0),
                url=url,
                title=src.get("title") or "",
                snippet=src.get("snippet") or "",
                item=_item_for(session, url) if url else None,
                body_source=src.get("body_source") or "",
            )
        )
    return sources


def _restore_input(session, claim: Claim, rows: list[dict]) -> None:
    wanted = {str(row.get("source_item_id")): row for row in rows if row.get("source_item_id")}
    for evidence in list(claim.evidence):
        key = str(evidence.source_item_id)
        if key not in wanted:
            claim.evidence.remove(evidence)
            session.delete(evidence)
            continue
        saved = wanted[key]
        evidence.evidence_type = EvidenceType(saved.get("evidence_type") or evidence.evidence_type.value)
        evidence.excerpt = saved.get("excerpt")
    session.flush()


def _policy_once(session, event, claim, plan, packet, result_dict, input_rows) -> dict:
    nested = session.begin_nested()
    try:
        _restore_input(session, claim, input_rows)
        service = VerificationService(session)
        service._comparison_checks = []
        preferred = preferred_domains(
            plan.jurisdiction,
            plan.verification_target.value,
            plan.subject.value,
            province=event.province,
            judicial_forum=plan.judicial_forum.value,
            claim_text=claim.canonical_text,
        )
        result = VerificationResult.model_validate(result_dict)
        before = _origins(claim, len(packet))
        _attached, _cited, primary, decision = service._apply_result(
            event, claim, packet, result, plan, preferred, False
        )
        after = _origins(claim, len(packet))
        return {
            "model_status": result.status.value,
            "model_confidence": result.confidence,
            "model_reason": (result.reason or "")[:400],
            "origins_before": before,
            "origins_after": after,
            "primary_supports": primary,
            "persistable_status": decision.status,
            "reason_code": decision.reason_code.value if decision.reason_code else None,
            "final_reason": decision.final_reason,
            "admitted": service._comparison_checks,
        }
    finally:
        nested.rollback()


def _gate_once(session, event, claim, plan, packet, assessment_dict, input_rows) -> dict:
    nested = session.begin_nested()
    try:
        _restore_input(session, claim, input_rows)
        service = VerificationService(session)
        service._comparison_checks = []
        preferred = preferred_domains(
            plan.jurisdiction,
            plan.verification_target.value,
            plan.subject.value,
            province=event.province,
            judicial_forum=plan.judicial_forum.value,
            claim_text=claim.canonical_text,
        )
        assessment = CheapClaimEvidenceAssessment.model_validate(assessment_dict)
        service._apply_judgements(event, claim, packet, assessment, preferred)
        primary = bool(service._primary_support_from_packet(claim, packet, preferred))
        if service._utterance_primary_supports(claim):
            primary = True
        escalate = needs_sol_after_assessment(
            claim,
            plan,
            assessment,
            primary_support=primary,
            admission_checks=service._comparison_checks,
        )
        return {
            "escalate": escalate,
            "ambiguous": assessment.ambiguous,
            "admitted_support": assessment_has_support(
                assessment, admission_checks=service._comparison_checks
            ),
            "primary_supports": primary,
            "origins": _origins(claim, len(packet)),
            "plan_primary_required": plan.primary_source_required,
            "plan_corroboration_required": plan.independent_corroboration_required,
        }
    finally:
        nested.rollback()


def _full_id(mapping: dict, prefix: str) -> str | None:
    for key in mapping or {}:
        if key.startswith(prefix) or key == prefix:
            return key
    return None


def _from_report(report: dict, claim_id: str, kind: str, side: str) -> dict | None:
    bucket = report["judgements"] if kind == "judgement" else report["assessments"]
    for row in bucket:
        if not row["claim_id"].startswith(claim_id[:8]) and row["claim_id"] != claim_id:
            continue
        block = row["persisted"] if side == "persisted" else row["executed"]
        model = row["persisted_model"] if side == "persisted" else row["executed_model"]
        return {"model": model, "body": block}
    return None


def evaluate_event(session, event_id: str, report: dict) -> dict:
    event = session.scalars(
        select(Event).where(Event.id == event_id).options(
            selectinload(Event.claims).selectinload(Claim.evidence)
        )
    ).one()
    run = session.scalars(
        select(PipelineRun)
        .where(PipelineRun.event_id == event.id, PipelineRun.stage == "verification")
        .order_by(PipelineRun.finished_at.desc())
    ).first()
    meta = (run.metadata_json if run else None) or {}
    claims = {str(row.id): row for row in event.claims}
    service = VerificationService(session)
    out_claims = []
    source_counts = session.scalar(select(func.count()).select_from(SourceItem))
    for cid, claim in claims.items():
        packet_json = (meta.get("packets") or {}).get(cid)
        plan_json = (meta.get("plans") or {}).get(cid)
        if not packet_json or not isinstance(plan_json, dict):
            continue
        plan = VerificationPlan.model_validate(plan_json)
        packet = _packet(session, packet_json)
        input_rows = (meta.get("input_evidence") or {}).get(cid) or []
        before = _fingerprint(claim)
        status_before = claim.status.value
        sources_before = session.scalar(
            select(func.count()).select_from(SourceItem).where(SourceItem.id.is_not(None))
        )
        stored_decision = (meta.get("decision_by_claim_id") or {}).get(cid) or {}
        judgements = []
        db_result = (meta.get("model_results") or {}).get(cid)
        if isinstance(db_result, dict):
            judgements.append(("pipeline", "stored-model", db_result))
        for side in ("persisted", "executed"):
            found = _from_report(report, cid, "judgement", side)
            if found and isinstance(found["body"], dict) and found["body"].get("evidence") is not None:
                judgements.append((side, found["model"], found["body"]))
        policy = []
        seen_models = set()
        for _side, model, body in judgements:
            if model in seen_models:
                continue
            seen_models.add(model)
            truncated = any(len((row.get("excerpt") or "")) >= 240 for row in body.get("evidence") or [])
            try:
                applied = _policy_once(session, event, claim, plan, packet, body, input_rows)
            except Exception as exc:
                applied = {"error": f"{type(exc).__name__}: {exc}"[:400]}
            applied["model"] = model
            applied["truncated_excerpt"] = truncated
            policy.append(applied)
            session.expire(claim, ["evidence", "status"])
            session.refresh(claim)
            if _fingerprint(claim) != before or claim.status.value != status_before:
                raise RuntimeError(f"la evidencia cambió en {cid}")
        gates = []
        db_assessment = (meta.get("assessments") or {}).get(cid)
        if isinstance(db_assessment, dict):
            gates.append(("pipeline", "stored-assessor", db_assessment, False))
        for side in ("persisted", "executed"):
            found = _from_report(report, cid, "assessment", side)
            if not found or not isinstance(found["body"], dict):
                continue
            body = found["body"]
            if "judgements" not in body:
                continue
            truncated = any(len((row.get("excerpt") or "")) >= 240 for row in body.get("judgements") or [])
            gates.append((side, found["model"], body, truncated))
        gate_rows = []
        seen_assessors = set()
        for _side, model, body, truncated in gates:
            if model in seen_assessors:
                continue
            seen_assessors.add(model)
            try:
                opened = _gate_once(session, event, claim, plan, packet, body, input_rows)
            except Exception as exc:
                opened = {"error": f"{type(exc).__name__}: {exc}"[:400]}
            opened["model"] = model
            opened["truncated_excerpt"] = truncated
            gate_rows.append(opened)
            session.expire(claim, ["evidence", "status"])
            session.refresh(claim)
            if _fingerprint(claim) != before or claim.status.value != status_before:
                raise RuntimeError(f"la compuerta alteró {cid}")
        if session.scalar(select(func.count()).select_from(SourceItem)) != source_counts:
            raise RuntimeError("se crearon fuentes y no se revirtieron")
        _ = sources_before
        out_claims.append(
            {
                "claim_id": cid,
                "claim": (claim.canonical_text or "")[:240],
                "priority": cid.startswith(PRIORITY),
                "stored_policy_status": stored_decision.get("status"),
                "stored_reason_code": stored_decision.get("reason_code"),
                "stored_final_reason": stored_decision.get("final_reason"),
                "plan": {
                    "target": plan.verification_target.value,
                    "subject": plan.subject.value,
                    "primary_source_required": plan.primary_source_required,
                    "independent_corroboration_required": plan.independent_corroboration_required,
                },
                "plan_prompt": service._plan_prompt(event, claim),
                "policy": policy,
                "gate": gate_rows,
                "escalated_originally": bool((meta.get("escalated") or {}).get(cid)),
            }
        )
    session.rollback()
    return {"event_id": event_id, "claims": out_claims}


def main() -> None:
    database = sys.argv[1]
    report_path = Path(sys.argv[2])
    output = Path(sys.argv[3])
    event_ids = sys.argv[4:]
    report = json.loads(report_path.read_text(encoding="utf-8"))
    session = SessionLocal()
    try:
        name = session.execute(text("select current_database()")).scalar_one()
        if name != database:
            raise SystemExit(f"base inesperada: {name}")
        payload = {"database": name, "events": [evaluate_event(session, event_id, report) for event_id in event_ids]}
        session.rollback()
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print("db", name, "events", len(payload["events"]), "bytes", output.stat().st_size)
    finally:
        session.close()


if __name__ == "__main__":
    main()
