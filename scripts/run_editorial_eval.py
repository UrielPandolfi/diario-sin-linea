#!/usr/bin/env python3
"""Editorial regression for Claim Extraction + Verification.

Modes:
  claims          Claims → Verification (default, cheaper)
  full-editorial  Research → Claims → Verification → Writing → Audit
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "apps" / "api"
FIXTURES = API_ROOT / "tests" / "fixtures" / "editorial_cases"
OUT_DIR = ROOT / ".editorial-evals"

sys.path.insert(0, str(API_ROOT))

CASE_FILES = (
    "01_federman.json",
    "02_tarifas.json",
    "03_mendoza.json",
)


def _load_env() -> None:
    for candidate in (ROOT / ".env", API_ROOT / ".env"):
        if not candidate.exists():
            continue
        for raw in candidate.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            import os

            os.environ.setdefault(key, value)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def _seed_case(session, case: dict):
    from app.core.text import content_fingerprint
    from app.domain.enums import IngestionMethod
    from app.schemas import EventCreate, SourceCreate, SourceItemCreate
    from app.services.event_service import EventService
    from app.services.source_item_service import SourceItemService
    from app.services.source_service import SourceService

    domain = case.get("source_domain") or urlparse(case["url"]).netloc
    source = SourceService(session).create(
        SourceCreate(
            name=case["source_name"],
            domain=domain,
            homepage_url=f"https://{domain}",
            preferred_ingestion_method=IngestionMethod.HTML,
            is_monitored=False,
            is_enabled=True,
        )
    )
    body = case["body"]
    published = _parse_dt(case.get("published_at"))
    item = SourceItemService(session).ingest(
        SourceItemCreate(
            source_id=source.id,
            url=case["url"],
            canonical_url=case["url"],
            content_hash=content_fingerprint(title=case["title"], body=body),
            title=case["title"],
            clean_text=body,
            excerpt=body[:400],
            published_at=published,
        )
    ).item
    event = EventService(session).create(
        EventCreate(
            title_internal=case["title"],
            event_type=case.get("event_type") or "unknown",
            source_item_id=item.id,
            started_at=published,
            province=case.get("province"),
            locality=case.get("locality"),
            short_summary=case.get("short_summary"),
        )
    )
    session.commit()
    return event


def _claim_rows(session, event_id):
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.models import Claim, ClaimEvidence, SourceItem

    stmt = (
        select(Claim)
        .options(
            selectinload(Claim.evidence).selectinload(ClaimEvidence.source_item).selectinload(SourceItem.source)
        )
        .where(Claim.event_id == event_id)
    )
    return list(session.scalars(stmt).unique())


def _article_row(session, event_id):
    from app.repositories import ArticleRepository

    return ArticleRepository(session).get_by_event_id(event_id)


def _snapshot_claims(claims) -> dict[str, dict]:
    rows = {}
    for claim in claims:
        rows[str(claim.id)] = {
            "canonical_text": claim.canonical_text,
            "claim_type": claim.claim_type,
            "importance": claim.importance.value,
            "status": claim.status.value,
            "occurred_at": claim.occurred_at.isoformat() if claim.occurred_at else None,
        }
    return rows


def _sources_for_claim(claim) -> list[dict]:
    rows = []
    for evidence in claim.evidence:
        item = evidence.source_item
        url = (item.url if item is not None else None) or evidence.source_url
        domain = None
        if item is not None and item.source is not None:
            domain = item.source.domain
        rows.append(
            {
                "evidence_type": evidence.evidence_type.value,
                "url": url,
                "domain": domain,
                "excerpt": evidence.excerpt,
            }
        )
    return rows


def _report_case(*, case, mode, event, claims_before, claims_after, verify, research, writing, audit, article) -> dict:
    selected = {row["claim_id"]: row for row in (verify or {}).get("selected") or []}
    plans = (verify or {}).get("plans") or {}
    queries = (verify or {}).get("queries") or {}
    temporal = (verify or {}).get("temporal_scope") or {}
    primary = (verify or {}).get("primary_found") or {}
    escalated = (verify or {}).get("escalated") or {}
    claim_reports = []
    for claim in claims_after:
        cid = str(claim.id)
        before = claims_before.get(cid) or {}
        claim_reports.append(
            {
                "canonical_text": claim.canonical_text,
                "claim_type": claim.claim_type,
                "importance": claim.importance.value,
                "status_initial": before.get("status"),
                "selected": cid in selected,
                "selection_reasons": (selected.get(cid) or {}).get("reasons") or [],
                "verification_plan": plans.get(cid),
                "temporal_scope": temporal.get(cid),
                "queries": queries.get(cid) or [],
                "sources_found": _sources_for_claim(claim),
                "primary_found": primary.get(cid),
                "status_final": claim.status.value,
                "escalated": escalated.get(cid),
            }
        )
    return {
        "id": case["id"],
        "mode": mode,
        "title": case["title"],
        "source": case["source_name"],
        "url": case["url"],
        "event_id": str(event.id),
        "research": research,
        "verification": {
            "verified": (verify or {}).get("verified"),
            "skipped_search": (verify or {}).get("skipped_search"),
            "error": (verify or {}).get("error"),
        },
        "claims": claim_reports,
        "writing": writing,
        "audit": audit,
        "headline": article.headline if article is not None else None,
        "summary": article.summary if article is not None else None,
        "body": article.body if article is not None else None,
    }


def _print_report(report: dict) -> None:
    print("=" * 88)
    print(f"CASO {report['id']}  [{report['mode']}]")
    print(report["title"])
    print(f"Fuente: {report['source']}")
    print("-" * 88)
    if not report["claims"]:
        print("Claims extraídos: (ninguno)")
    for index, claim in enumerate(report["claims"], start=1):
        print(f"\nClaim {index}")
        print(f"  texto: {claim['canonical_text']}")
        print(f"  type/importancia: {claim['claim_type']} / {claim['importance']}")
        print(f"  status inicial: {claim['status_initial']}")
        print(f"  Verification seleccionado: {claim['selected']} {claim['selection_reasons']}")
        plan = claim["verification_plan"] or {}
        print(f"  VerificationPlan: {json.dumps(plan, ensure_ascii=False)}")
        print(f"  temporal_scope: {claim['temporal_scope']}")
        print(f"  queries: {claim['queries']}")
        print(f"  fuentes encontradas: {json.dumps(claim['sources_found'], ensure_ascii=False)}")
        print(f"  fuente primaria encontrada: {claim['primary_found']}")
        print(f"  status final: {claim['status_final']}")
        print(f"  escaló a Sol: {claim['escalated']}")
    print("\nheadline:", report["headline"])
    print("summary:", report["summary"])
    print("body:\n", report["body"] or "")
    if report.get("audit"):
        print("audit passed:", (report["audit"] or {}).get("passed"))


def run_case(session, case: dict, *, mode: str) -> dict:
    from app.services.audit_service import AuditService
    from app.services.claim_service import ClaimService
    from app.services.research_service import ResearchService
    from app.services.verification_service import VerificationService
    from app.services.writing_service import WritingService

    event = _seed_case(session, case)
    research = None
    writing = None
    audit = None
    trigger = f"editorial_eval:{case['id']}"

    if mode == "full-editorial":
        research = ResearchService(session).research(event.id, trigger=trigger)
        session.commit()
        if research.get("error"):
            raise RuntimeError(f"research failed: {research['error']}")

    claims_result = ClaimService(session).resolve(event.id, trigger=trigger)
    session.commit()
    if claims_result.get("error"):
        raise RuntimeError(f"claims failed: {claims_result['error']}")
    claims_before = _snapshot_claims(_claim_rows(session, event.id))

    verify = VerificationService(session).verify(event.id, trigger=trigger)
    session.commit()
    if verify.get("error"):
        raise RuntimeError(f"verification failed: {verify['error']}")
    claims_after = _claim_rows(session, event.id)

    if mode == "full-editorial":
        writing = WritingService(session).write(event.id, trigger=trigger)
        session.commit()
        if writing.get("error"):
            raise RuntimeError(f"writing failed: {writing['error']}")
        audit = AuditService(session).audit(event.id, trigger=trigger)
        session.commit()
        if audit.get("error"):
            raise RuntimeError(f"audit failed: {audit['error']}")

    article = _article_row(session, event.id) if mode == "full-editorial" else None
    return _report_case(
        case=case,
        mode=mode,
        event=event,
        claims_before=claims_before,
        claims_after=claims_after,
        verify=verify,
        research=research,
        writing=writing,
        audit=audit,
        article=article,
    )


def _require_providers(mode: str) -> None:
    from app.providers.base import ProviderNotConfiguredError
    from app.providers.registry import ModelRole, get_search_provider, get_structured_provider

    roles = [
        ModelRole.LIGHT_PROCESSING,
        ModelRole.CLAIM_RESOLUTION,
        ModelRole.ULTRA_LIGHT_PROCESSING,
        ModelRole.VERIFICATION,
    ]
    if mode == "full-editorial":
        roles.extend([ModelRole.WRITING, ModelRole.AUDITING])
    missing: list[str] = []
    for role in roles:
        try:
            get_structured_provider(role)
        except ProviderNotConfiguredError as exc:
            missing.append(str(exc))
    try:
        get_search_provider()
    except ProviderNotConfiguredError as exc:
        missing.append(str(exc))
    if missing:
        joined = "\n".join(f"- {item}" for item in missing)
        raise SystemExit(
            "Faltan providers para el eval editorial. Configurá las keys y roles en .env:\n"
            f"{joined}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Eval editorial de Claims + Verification")
    parser.add_argument(
        "--mode",
        choices=("claims", "full-editorial"),
        default="claims",
        help="claims: Claims+Verification. full-editorial: Research→Claims→Verification→Writing→Audit",
    )
    args = parser.parse_args()
    _load_env()
    _require_providers(args.mode)

    from app.core.db import SessionLocal

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    reports = []
    session = SessionLocal()
    try:
        for name in CASE_FILES:
            case = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
            print(f"\nProcesando {case['id']}...")
            try:
                report = run_case(session, case, mode=args.mode)
                reports.append(report)
                _print_report(report)
            except Exception as exc:
                session.rollback()
                print(f"ERROR en caso {case.get('id')}: {exc}", file=sys.stderr)
                reports.append(
                    {
                        "id": case.get("id"),
                        "mode": args.mode,
                        "title": case.get("title"),
                        "error": str(exc),
                        "claims": [],
                    }
                )
    finally:
        session.close()

    payload = {"mode": args.mode, "generated_at": datetime.now().isoformat(), "cases": reports}
    out = OUT_DIR / f"{stamp}-{args.mode}.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nJSON guardado en {out}")
    if any(row.get("error") for row in reports) or len(reports) < len(CASE_FILES):
        return 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
