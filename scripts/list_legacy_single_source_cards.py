#!/usr/bin/env python3
"""Read-only: published notes whose public card may have shown reprints as several sources.

Does not publish, rewrite, or create Correction. A material headline/body error
still needs EditorialService.revise; this list is for reaudit of the text, not the card.

Run from apps/api or repo root with DATABASE_URL (Compose: docker compose exec api python scripts/...).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_HOST_API = ROOT / "apps" / "api"
API_ROOT = _HOST_API if (_HOST_API / "app").is_dir() else ROOT
sys.path.insert(0, str(API_ROOT))

from sqlalchemy import func, select  # noqa: E402

from app.core.db import SessionLocal  # noqa: E402
from app.domain.enums import ArticleStatus, ClaimStatus, PipelineStatus  # noqa: E402
from app.models import Article, Claim, ClaimEvidence, Event, PipelineRun  # noqa: E402
from app.services.verification_outcome import VERIFICATION_STAGE  # noqa: E402


def _sol_reason(meta: dict, claim_id: str) -> str:
    for row in meta.get("sol") or []:
        if isinstance(row, dict) and str(row.get("claim_id")) == claim_id:
            return str(row.get("reason") or row.get("llm_reason") or "")
    decision = (meta.get("decision_by_claim_id") or {}).get(claim_id) or {}
    return str(decision.get("llm_reason") or decision.get("final_reason") or "")


def main() -> int:
    session = SessionLocal()
    try:
        reprints = session.execute(
            select(
                Event.id,
                Event.public_id,
                Article.slug,
                Claim.id,
                Claim.canonical_text,
                func.count(func.distinct(ClaimEvidence.source_item_id)),
            )
            .join(Article, Article.event_id == Event.id)
            .join(Claim, Claim.event_id == Event.id)
            .join(ClaimEvidence, ClaimEvidence.claim_id == Claim.id)
            .where(Article.status == ArticleStatus.PUBLISHED)
            .where(Article.published_at.is_not(None))
            .where(Claim.status == ClaimStatus.SINGLE_SOURCE)
            .group_by(Event.id, Event.public_id, Article.slug, Claim.id, Claim.canonical_text)
            .having(func.count(func.distinct(ClaimEvidence.source_item_id)) >= 2)
        ).all()

        independent_copy: list[dict] = []
        stmt = (
            select(Event.id, Event.public_id, Article.slug, Claim.id, Claim.status, Claim.canonical_text, PipelineRun.metadata_json)
            .join(Article, Article.event_id == Event.id)
            .join(Claim, Claim.event_id == Event.id)
            .join(PipelineRun, PipelineRun.event_id == Event.id)
            .where(Article.status == ArticleStatus.PUBLISHED)
            .where(Article.published_at.is_not(None))
            .where(Claim.status != ClaimStatus.SUPPORTED)
            .where(PipelineRun.stage == VERIFICATION_STAGE)
            .where(PipelineRun.status == PipelineStatus.SUCCESS)
            .order_by(PipelineRun.finished_at.desc())
        )
        seen: set[str] = set()
        for event_id, public_id, slug, claim_id, status, text, meta in session.execute(stmt):
            key = f"{event_id}:{claim_id}"
            if key in seen:
                continue
            reason = _sol_reason(meta or {}, str(claim_id))
            if "independiente" not in reason.casefold():
                continue
            seen.add(key)
            independent_copy.append(
                {
                    "event_id": str(event_id),
                    "public_id": str(public_id),
                    "slug": slug,
                    "claim_id": str(claim_id),
                    "status": status.value if hasattr(status, "value") else str(status),
                    "canonical_text": text,
                    "reason_snippet": reason[:240],
                }
            )

        payload = {
            "single_source_many_source_items": [
                {
                    "event_id": str(event_id),
                    "public_id": str(public_id),
                    "slug": slug,
                    "claim_id": str(claim_id),
                    "canonical_text": text,
                    "source_item_count": int(count),
                }
                for event_id, public_id, slug, claim_id, text, count in reprints
            ],
            "non_supported_with_independiente_in_sol_reason": independent_copy,
            "note": (
                "Serializer updates the card without a new version. "
                "Correction only if the published text (not the card) is still wrong."
            ),
        }
        json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
