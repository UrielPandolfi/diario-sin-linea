"""Lote manual en la base aislada con la configuración definitiva.

Beat no se enciende. AUTO_PUBLISH queda en false durante el pipeline.
La portada y la publicación solo corren después, y solo para candidatas
aprobadas, guardando la imagen en esta base. No envía correo.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

ORIGINAL_ENV = Path(r"E:\Diario Sin Línea\.env")
FEED = "https://www.elciudadanoweb.com/feed"
BUDGET_CAP = Decimal("3")
TARGET_EVENTS = 5
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
    "COST_PROFILE_ROLES",
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
    os.environ["COST_PROFILE_ROLES"] = "verification,auditing"
    os.environ["SEARCH_CACHE_ENABLED"] = "true"
    os.environ["VERIFICATION_REUSE_ENABLED"] = "true"
    os.environ["ARTICLE_IMAGE_ENABLED"] = "false"
    os.environ["USAGE_ENVIRONMENT"] = "experiment"
    # El correo transaccional del entorno original no se usa: esta corrida no llama a Resend.
    os.environ["RESEND_API_KEY"] = ""


_load_env()

from sqlalchemy import text  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.db import SessionLocal  # noqa: E402
from app.domain.enums import IngestionMethod  # noqa: E402
from app.providers.registry import ModelRole, _structured_role_config  # noqa: E402
from app.schemas import SourceCreate  # noqa: E402
from app.services.app_settings import AppSettingsService  # noqa: E402
from app.services.audit_service import AuditService  # noqa: E402
from app.services.call_budget import CallBudgetExceeded, install_budget  # noqa: E402
from app.services.claim_service import ClaimService  # noqa: E402
from app.services.detection_service import DetectionService  # noqa: E402
from app.services.ingestion_service import IngestionService  # noqa: E402
from app.services.publish_service import PublishService  # noqa: E402
from app.services.research_service import ResearchService  # noqa: E402
from app.services.source_service import SourceService  # noqa: E402
from app.services.verification_service import VerificationService  # noqa: E402
from app.services.writing_service import WritingService, should_enqueue_write  # noqa: E402

REPORT = Path(r"E:\temp\sinlinea_batch_report.json")


def _spent(session) -> tuple[Decimal, int, int]:
    total, unknown, calls = session.execute(
        text(
            """
            select coalesce(sum(estimated_cost_usd), 0),
                   count(*) filter (where estimated_cost_usd is null or cost_status <> 'calculated'),
                   count(*)
            from llm_usages
            """
        )
    ).one()
    return Decimal(total), int(unknown), int(calls)


def _effective_models() -> dict:
    rows = {}
    for role in ModelRole:
        if role == ModelRole.EMBEDDING:
            settings = get_settings()
            rows[role.value] = {
                "provider": settings.embedding_provider,
                "model": settings.embedding_model,
                "thinking": None,
            }
            continue
        provider, model, thinking = _structured_role_config(role)
        rows[role.value] = {"provider": provider, "model": model, "thinking": thinking}
    return rows


def _assert_config(models: dict) -> None:
    settings = get_settings()
    problems = []
    if settings.cost_profile != "candidate":
        problems.append("cost_profile")
    if settings.cost_profile_roles != "verification,auditing":
        problems.append("roles")
    if not settings.search_cache_enabled or not settings.verification_reuse_enabled:
        problems.append("reuse")
    if settings.auto_publish:
        problems.append("auto_publish")
    verification = models["verification"]
    auditing = models["auditing"]
    ultra = models["ultra_light_processing"]
    if (verification["provider"], verification["model"], verification["thinking"]) != (
        "deepseek",
        "deepseek-v4-pro",
        "disabled",
    ):
        problems.append("verification")
    if (auditing["provider"], auditing["model"], auditing["thinking"]) != (
        "deepseek",
        "deepseek-flash",
        "disabled",
    ):
        problems.append("auditing")
    if (ultra["provider"], ultra["model"]) != ("openai", "gpt-5-nano"):
        problems.append("ultra_light")
    if models["image_prompt"]["model"] != "deepseek-chat":
        problems.append("image_prompt")
    if models["claim_resolution"]["model"] != "deepseek-chat":
        problems.append("claim_resolution")
    if problems:
        raise SystemExit("configuracion inesperada: " + ",".join(problems))


def _brief(value: dict) -> dict:
    if not isinstance(value, dict):
        return {"value": str(value)[:200]}
    kept = {}
    for key in (
        "skipped",
        "reason",
        "error",
        "written",
        "passed",
        "verified",
        "reused",
        "stopped",
        "published",
        "created",
        "filtered",
        "structural_block",
        "rewrite_count",
    ):
        if key in value:
            kept[key] = value.get(key)
    return kept


def _claims_changed(result: dict) -> bool:
    if "changed" in result:
        return bool(result.get("changed"))
    persisted = result.get("persisted")
    return persisted is None or int(persisted) > 0


def _run_stage(session, name: str, fn) -> tuple[dict, bool]:
    try:
        result = fn()
        session.commit()
        return result if isinstance(result, dict) else {"value": str(result)[:200]}, False
    except CallBudgetExceeded as exc:
        session.rollback()
        return {"stopped": "budget", "reason": str(exc)[:300]}, True
    except Exception as exc:
        session.rollback()
        return {"error": type(exc).__name__, "detail": str(exc)[:400]}, True


def main() -> None:
    get_settings.cache_clear()
    settings = get_settings()
    settings.monitored_source_poll_limit = 15
    settings.article_image_enabled = False
    settings.auto_publish = False
    models = _effective_models()
    _assert_config(models)
    session = SessionLocal()
    started = datetime.now(timezone.utc)
    try:
        current = session.execute(text("SELECT current_database()")).scalar_one()
        if current != "sin_linea_costos":
            raise SystemExit(f"base inesperada: {current}")
        spent_before, unknown_before, calls_before = _spent(session)
        remaining = BUDGET_CAP - spent_before
        if remaining <= 0:
            raise SystemExit(f"sin resto de presupuesto: {spent_before}")
        install_budget(remaining)
        AppSettingsService(session).set_auto_poll_enabled(False)
        session.commit()
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
        print(
            "poll",
            {"seen": poll.seen, "created": poll.created, "updated": poll.updated, "items": len(poll.item_ids)},
            flush=True,
        )
        created_events: list[str] = []
        discards: list[dict] = []
        processed: list[dict] = []
        budget_stopped = False
        pending_stage = None
        for item_id in list(poll.item_ids):
            if len(created_events) >= TARGET_EVENTS or budget_stopped:
                break
            detected, stopped = _run_stage(
                session, "detect", lambda item_id=item_id: DetectionService(session).detect(item_id)
            )
            print("detect", item_id, _brief(detected), flush=True)
            if stopped:
                budget_stopped = detected.get("stopped") == "budget"
                pending_stage = "event_detection"
                discards.append({"item_id": str(item_id), "result": _brief(detected)})
                break
            event_id = detected.get("event_id")
            if not event_id or not detected.get("created"):
                discards.append({"item_id": str(item_id), "result": _brief(detected)})
                continue
            event_uuid = UUID(str(event_id))
            stage_results = {"detect": _brief(detected)}
            event_stopped = False
            research, stage_stopped = _run_stage(
                session,
                "research",
                lambda event_uuid=event_uuid: ResearchService(session).research(event_uuid, trigger="manual_batch"),
            )
            stage_results["research"] = _brief(research)
            print("stage", event_uuid, "research", stage_results["research"], flush=True)
            continue_pipeline = not stage_stopped and not research.get("skipped")
            if stage_stopped:
                event_stopped = True
                budget_stopped = research.get("stopped") == "budget"
                pending_stage = "research"
            claims = {}
            if continue_pipeline:
                claims, stage_stopped = _run_stage(
                    session,
                    "claims",
                    lambda event_uuid=event_uuid: ClaimService(session).resolve(
                        event_uuid, trigger="manual_batch", source_item_id=None
                    ),
                )
                stage_results["claims"] = _brief(claims)
                print("stage", event_uuid, "claims", stage_results["claims"], flush=True)
                if stage_stopped:
                    event_stopped = True
                    budget_stopped = claims.get("stopped") == "budget"
                    pending_stage = "claims"
                    continue_pipeline = False
                elif claims.get("skipped") or not _claims_changed(claims):
                    continue_pipeline = False
            if continue_pipeline:
                verify, stage_stopped = _run_stage(
                    session,
                    "verify",
                    lambda event_uuid=event_uuid: VerificationService(session).verify(event_uuid, trigger="manual_batch"),
                )
                stage_results["verify"] = _brief(verify)
                print("stage", event_uuid, "verify", stage_results["verify"], flush=True)
                if stage_stopped:
                    event_stopped = True
                    budget_stopped = verify.get("stopped") == "budget"
                    pending_stage = "verify"
                elif not verify.get("skipped") and not verify.get("error") and should_enqueue_write(session, event_uuid):
                    write, stage_stopped = _run_stage(
                        session,
                        "write",
                        lambda event_uuid=event_uuid: WritingService(session).write(event_uuid, trigger="manual_batch"),
                    )
                    stage_results["write"] = _brief(write)
                    print("stage", event_uuid, "write", stage_results["write"], flush=True)
                    if stage_stopped:
                        event_stopped = True
                        budget_stopped = write.get("stopped") == "budget"
                        pending_stage = "write"
                    elif write.get("written") is True:
                        audit, stage_stopped = _run_stage(
                            session,
                            "audit",
                            lambda event_uuid=event_uuid: AuditService(session).audit(event_uuid, trigger="manual_batch"),
                        )
                        stage_results["audit"] = _brief(audit)
                        print("stage", event_uuid, "audit", stage_results["audit"], flush=True)
                        if stage_stopped:
                            event_stopped = True
                            budget_stopped = audit.get("stopped") == "budget"
                            pending_stage = "audit"
            created_events.append(str(event_uuid))
            title = session.execute(
                text("select title_internal from events where id = :id"),
                {"id": event_uuid},
            ).scalar_one_or_none()
            processed.append(
                {
                    "event_id": str(event_uuid),
                    "title": (title or "")[:180],
                    "stopped": event_stopped,
                    "stages": stage_results,
                }
            )
            if budget_stopped:
                break

        publications = []
        if not budget_stopped:
            settings.article_image_enabled = True
            for row in processed:
                if row["stages"].get("audit", {}).get("passed") is not True:
                    continue
                event_uuid = UUID(row["event_id"])
                published, stage_stopped = _run_stage(
                    session,
                    "publish",
                    lambda event_uuid=event_uuid: PublishService(session).publish(event_uuid, trigger="manual_batch"),
                )
                hero = None
                if not stage_stopped and published.get("published"):
                    hero = session.execute(
                        text(
                            """
                            select a.hero_image_url, a.published_version, a.status,
                                   (h.article_id is not null) as stored
                            from articles a
                            left join article_hero_images h on h.article_id = a.id
                            where a.event_id = :id
                            """
                        ),
                        {"id": event_uuid},
                    ).one()
                publications.append(
                    {
                        "event_id": row["event_id"],
                        "result": _brief(published) | {"published": published.get("published"), "reason": published.get("reason")},
                        "hero_url": None if hero is None else hero[0],
                        "published_version": None if hero is None else hero[1],
                        "article_status": None if hero is None else str(hero[2]),
                        "image_stored_locally": None if hero is None else bool(hero[3]),
                        "stopped": stage_stopped,
                    }
                )
                print("publish", row["event_id"], publications[-1], flush=True)
                if stage_stopped:
                    budget_stopped = published.get("stopped") == "budget"
                    pending_stage = "publish"
                    break
        spent_after, unknown_after, calls_after = _spent(session)
        usage = session.execute(
            text(
                """
                select coalesce(event_id::text, ''),
                       coalesce(stage, ''),
                       coalesce(model_role, ''),
                       coalesce(model_requested, ''),
                       coalesce(model_reported, ''),
                       count(*),
                       coalesce(sum(estimated_cost_usd), 0),
                       count(*) filter (where estimated_cost_usd is null or cost_status <> 'calculated'),
                       count(*) filter (where coalesce(request_options->>'cache_hit', 'false') = 'true'),
                       count(*) filter (where coalesce(request_options->'thinking'->>'type', '') = 'disabled')
                from llm_usages
                where created_at >= :started
                group by 1, 2, 3, 4, 5
                order by 1, 2
                """
            ),
            {"started": started},
        ).fetchall()
        report = {
            "database": current,
            "started": started.isoformat(),
            "models": models,
            "poll": {
                "seen": poll.seen,
                "created": poll.created,
                "updated": poll.updated,
                "items": len(poll.item_ids),
                "window": settings.monitored_source_poll_limit,
                "production_max_new_events_per_poll": os.environ.get("MAX_NEW_EVENTS_PER_POLL"),
            },
            "spent_before": str(spent_before),
            "spent_after": str(spent_after),
            "delta": str(spent_after - spent_before),
            "unknown_before": unknown_before,
            "unknown_after": unknown_after,
            "calls_before": calls_before,
            "calls_after": calls_after,
            "budget_stopped": budget_stopped,
            "pending_stage": pending_stage,
            "discards": discards,
            "events": processed,
            "publications": publications,
            "usage": [
                {
                    "event_id": row[0] or None,
                    "stage": row[1],
                    "role": row[2],
                    "requested": row[3],
                    "reported": row[4],
                    "calls": int(row[5]),
                    "usd": str(row[6]),
                    "unknown": int(row[7]),
                    "cache_hits": int(row[8]),
                    "thinking_disabled": int(row[9]),
                }
                for row in usage
            ],
        }
        REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print("delta", report["delta"], "events", len(processed), "published", len(publications), flush=True)
    finally:
        session.close()


if __name__ == "__main__":
    main()
