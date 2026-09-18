"""Explicit single-claim recheck through Claims and Verification; never publishes."""
import argparse
import json
from uuid import UUID

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models import Claim, PipelineRun
from app.services.claim_service import ClaimService
from app.services.verification_service import VerificationService


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claim-id", required=True, type=UUID)
    args = parser.parse_args()
    with SessionLocal() as session:
        claim = session.get(Claim, args.claim_id)
        if claim is None:
            raise SystemExit("claim_not_found")
        event_id = claim.event_id
        print(json.dumps({"claim_id": str(claim.id), "status_before": claim.status.value}, ensure_ascii=False), flush=True)
        for service in (ClaimService(session), VerificationService(session)):
            action = service.resolve if isinstance(service, ClaimService) else service.verify
            result = action(event_id, trigger="admin", claim_id=args.claim_id,
                            context={"reason": "explicit_proposition_comparison_recheck"})
            session.commit()
            stage = "claim_resolution" if isinstance(service, ClaimService) else "verification"
            run = session.scalars(select(PipelineRun).where(PipelineRun.event_id == event_id, PipelineRun.stage == stage)
                                  .order_by(PipelineRun.started_at.desc())).first()
            print(json.dumps({"stage": stage, "run_id": str(run.id) if run else None,
                              "status": run.status.value if run else None, "error": result.get("error")}, ensure_ascii=False), flush=True)
            if result.get("error") or result.get("skipped"):
                raise SystemExit(1)
        session.refresh(claim)
        print(json.dumps({"claim_id": str(claim.id), "canonical_text": claim.canonical_text, "status_after": claim.status.value,
                          "evidence": [{"source_url": e.source_url, "relation": e.evidence_type.value, "excerpt": e.excerpt} for e in claim.evidence]},
                         ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
