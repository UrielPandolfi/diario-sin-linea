"""Poll acotado del feed en la base aislada. No publica, no levanta Beat, no toca la base operativa."""

from __future__ import annotations

import os
import sys
from decimal import Decimal
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

ORIGINAL_ENV = Path(r"E:\Diario Sin Línea\.env")
FEED = "https://www.elciudadanoweb.com/feed"
BUDGET = Decimal("2")
SKIP_PREFIXES = (
    "DATABASE_URL",
    "TEST_DATABASE_URL",
    "REDIS_URL",
    "AUTO_PUBLISH",
    "COST_PROFILE",
    "USAGE_ENVIRONMENT",
    "SEARCH_CACHE_ENABLED",
    "VERIFICATION_REUSE_ENABLED",
    "COST_CALL_BUDGET_USD",
    "ARTICLE_IMAGE_ENABLED",
)


def _load_env() -> None:
    for line in ORIGINAL_ENV.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.startswith(SKIP_PREFIXES):
            continue
        os.environ.setdefault(key, value.strip().strip('"').strip("'"))
    os.environ["DATABASE_URL"] = "postgresql+psycopg://sin_linea:sin_linea@127.0.0.1:55432/sin_linea_costos"
    os.environ["REDIS_URL"] = "redis://127.0.0.1:6380/2"
    os.environ["AUTO_PUBLISH"] = "false"
    os.environ["COST_PROFILE"] = "candidate"
    os.environ["USAGE_ENVIRONMENT"] = "experiment"
    os.environ["SEARCH_CACHE_ENABLED"] = "true"
    os.environ["VERIFICATION_REUSE_ENABLED"] = "true"
    os.environ["ARTICLE_IMAGE_ENABLED"] = "false"
    os.environ["COST_CALL_BUDGET_USD"] = "2"
    os.environ["JOB_MAX_RETRIES"] = "1"
    os.environ["MONITORED_SOURCE_POLL_LIMIT"] = "8"


_load_env()

from sqlalchemy import text  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.db import SessionLocal  # noqa: E402
from app.domain.enums import IngestionMethod  # noqa: E402
from app.schemas import SourceCreate  # noqa: E402
from app.services.app_settings import AppSettingsService  # noqa: E402
from app.services.audit_service import AuditService  # noqa: E402
from app.services.call_budget import CallBudgetExceeded, install_budget  # noqa: E402
from app.services.claim_service import ClaimService  # noqa: E402
from app.services.detection_service import DetectionService  # noqa: E402
from app.services.ingestion_service import IngestionService  # noqa: E402
from app.services.research_service import ResearchService  # noqa: E402
from app.services.source_service import SourceService  # noqa: E402
from app.services.verification_service import VerificationService  # noqa: E402
from app.services.writing_service import WritingService  # noqa: E402


def main() -> None:
    settings = get_settings()
    settings.monitored_source_poll_limit = 8
    settings.article_image_enabled = False
    settings.auto_publish = False
    settings.cost_profile = "candidate"
    settings.search_cache_enabled = True
    settings.verification_reuse_enabled = True
    budget = install_budget(BUDGET)
    session = SessionLocal()
    current = session.execute(text("SELECT current_database()")).scalar_one()
    if current != "sin_linea_costos":
        raise SystemExit(f"base inesperada: {current}")
    AppSettingsService(session).set_auto_poll_enabled(False)
    from sqlalchemy import select

    from app.models import Source

    source = session.scalars(select(Source).where(Source.feed_url == FEED)).first()
    if source is None:
        source = SourceService(session).create(
            SourceCreate(
                name="El Ciudadano",
                preferred_ingestion_method=IngestionMethod.RSS,
                feed_url=FEED,
                is_monitored=True,
                is_enabled=True,
            )
        )
        session.commit()
    poll = IngestionService(session).poll_source(source.id)
    session.commit()
    print("poll", {"seen": poll.seen, "created": poll.created, "updated": poll.updated, "items": len(poll.item_ids)})
    created_events = []
    for item_id in list(poll.item_ids):
        if len(created_events) >= 2:
            break
        try:
            detected = DetectionService(session).detect(item_id)
            session.commit()
        except CallBudgetExceeded as exc:
            session.rollback()
            print("budget_stop", "detect", str(exc))
            break
        except Exception as exc:
            session.rollback()
            print("detect_error", type(exc).__name__, str(exc)[:300])
            continue
        event_id = detected.get("event_id")
        print("detect", {k: detected.get(k) for k in ("created", "event_id", "reason", "skipped")})
        if not event_id or not detected.get("created"):
            continue
        event_uuid = UUID(str(event_id))
        stages = (
            ("research", lambda: ResearchService(session).research(event_uuid, trigger="cost_probe")),
            ("claims", lambda: ClaimService(session).resolve(event_uuid, trigger="cost_probe", source_item_id=item_id)),
            ("verify", lambda: VerificationService(session).verify(event_uuid, trigger="cost_probe")),
            ("write", lambda: WritingService(session).write(event_uuid, trigger="cost_probe")),
            ("audit", lambda: AuditService(session).audit(event_uuid, trigger="cost_probe")),
        )
        stage_results = {}
        stopped = False
        for name, fn in stages:
            try:
                stage_results[name] = fn()
                session.commit()
            except CallBudgetExceeded as exc:
                session.rollback()
                stage_results[name] = {"stopped": "budget", "reason": str(exc)}
                stopped = True
                break
            except Exception as exc:
                session.rollback()
                stage_results[name] = {"error": type(exc).__name__, "detail": str(exc)[:400]}
                stopped = True
                break
        created_events.append(str(event_uuid))
        print("event", event_uuid, {name: _brief(value) for name, value in stage_results.items()})
        if stopped:
            break
    costs = session.execute(
        text(
            """
            SELECT event_id::text, count(*),
                   coalesce(sum(estimated_cost_usd) FILTER (WHERE cost_status = 'calculated'), 0),
                   count(*) FILTER (WHERE cost_status = 'unknown'),
                   count(*) FILTER (WHERE coalesce(request_options->>'cache_hit','false') = 'true')
            FROM llm_usages
            WHERE environment = 'experiment' AND event_id IS NOT NULL
            GROUP BY event_id
            """
        )
    ).fetchall()
    published = session.execute(
        text("SELECT count(*) FROM articles WHERE published_version IS NOT NULL")
    ).scalar_one()
    print("published_versions", published)
    print("spent_budget", str(budget.spent))
    for row in costs:
        print("event_cost", row)
    print("events", created_events)


def _brief(value: dict) -> dict:
    if not isinstance(value, dict):
        return {"value": str(value)[:200]}
    keys = ("skipped", "reason", "error", "written", "passed", "verified", "reused", "stopped", "published")
    return {key: value.get(key) for key in keys if key in value}


if __name__ == "__main__":
    main()
