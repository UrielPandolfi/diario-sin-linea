"""Comparación acotada A–D. No reingesta, no busca afuera, no genera portadas ni publica.

El presupuesto se reserva antes de cada llamada. Si no alcanza, la llamada no se hace.
"""

from __future__ import annotations

import json
import os
import sys
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "apps" / "api"
sys.path.insert(0, str(API))

ORIGINAL_ENV = Path(r"E:\Diario Sin Línea\.env")
CASES = Path(__file__).with_name("frozen_cases.json")
REPORT = Path(__file__).with_name("cost_scenario_report.json")
BUDGET = Decimal("2.97")

SKIP_PREFIXES = (
    "DATABASE_URL",
    "TEST_DATABASE_URL",
    "REDIS_URL",
    "AUTO_PUBLISH",
    "COST_PROFILE",
    "USAGE_ENVIRONMENT",
    "SEARCH_CACHE_ENABLED",
    "VERIFICATION_REUSE_ENABLED",
)


def _load_original_env() -> None:
    if not ORIGINAL_ENV.exists():
        raise SystemExit("falta el entorno original para las claves")
    for line in ORIGINAL_ENV.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.startswith(SKIP_PREFIXES):
            continue
        os.environ.setdefault(key, value.strip().strip('"').strip("'"))
    os.environ["DATABASE_URL"] = "postgresql+psycopg://sin_linea:sin_linea@127.0.0.1:55432/sin_linea_costos"
    os.environ["TEST_DATABASE_URL"] = "postgresql+psycopg://sin_linea:sin_linea@127.0.0.1:55432/sin_linea_costos_test"
    os.environ["REDIS_URL"] = "redis://127.0.0.1:6380/2"
    os.environ["AUTO_PUBLISH"] = "false"
    os.environ["USAGE_ENVIRONMENT"] = "experiment"
    os.environ["ARTICLE_IMAGE_ENABLED"] = "false"
    os.environ["SEARCH_CACHE_ENABLED"] = "false"
    os.environ["VERIFICATION_REUSE_ENABLED"] = "false"
    os.environ["JOB_MAX_RETRIES"] = "1"
    os.environ["COST_PROFILE"] = "current"


_load_original_env()

from pydantic import BaseModel  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.db import SessionLocal  # noqa: E402
from app.providers.openai_provider import OpenAIStructuredProvider  # noqa: E402
from app.providers.registry import ModelRole, get_structured_provider  # noqa: E402
from app.services.call_budget import CallBudgetExceeded, install_budget  # noqa: E402


class ClaimJudgment(BaseModel):
    decision: str
    certainty: str
    attributed_to: str
    supported_by_excerpt: str
    note: str


class AuditCheck(BaseModel):
    passed: str
    problems: list[str]
    note: str


def _prompt(case: dict, stage: str) -> tuple[str, str]:
    claims = "\n".join(
        f"- {row['text']} (tipo {row['type']}, sujeto {row['subject']})" for row in case["claims"][:4]
    )
    sources = "\n".join(
        f"Fuente: {row['title']}\n{row['excerpt']}" for row in case["sources"][:2]
    )
    system = (
        "Sos el criterio editorial de Sin Línea. Usá solo el texto de las fuentes. "
        "No completes datos que no estén. Una afirmación refutada puede informarse "
        "si está atribuida y explicada. Respondé JSON."
    )
    if stage == "verification":
        user = (
            f"Suceso: {case['title']}\n\nAfirmaciones:\n{claims}\n\nFuentes:\n{sources}\n\n"
            "Juzgá la primera afirmación. decision: supported, insufficient o contradicted."
        )
        return system, user
    headline = (case.get("article") or {}).get("headline") or case["title"]
    user = (
        f"Titular: {headline}\n\nFuentes:\n{sources}\n\n"
        "¿El titular atribuye de más o afirma algo que las fuentes no dicen? passed true solo si no hay ese problema."
    )
    return system, user


def _provider_for(scenario: str, stage: str):
    settings = get_settings()
    if scenario in {"C", "D"}:
        settings.cost_profile = "candidate"
        settings.cost_profile_roles = "verification,auditing"
        role = ModelRole.VERIFICATION if stage == "verification" else ModelRole.AUDITING
        return get_structured_provider(role)
    settings.cost_profile = "current"
    if stage == "verification":
        return OpenAIStructuredProvider(
            api_key=settings.openai_api_key or "",
            model=settings.verification_model or "gpt-4o",
            provider_name="openai",
        )
    return OpenAIStructuredProvider(
        api_key=settings.openai_api_key or "",
        model=settings.auditing_model or "gpt-4o",
        provider_name="openai",
    )


def main() -> None:
    session = SessionLocal()
    current = session.execute(text("SELECT current_database()")).scalar_one()
    session.close()
    if current != "sin_linea_costos":
        raise SystemExit(f"base inesperada: {current}")
    budget = install_budget(BUDGET)
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    seen: dict[str, dict] = {}
    rows = []
    skipped = []
    for scenario, reuse in (("A", False), ("B", True), ("C", False), ("D", True)):
        for case in cases:
            for stage in ("verification", "audit"):
                system, user = _prompt(case, stage)
                schema = ClaimJudgment if stage == "verification" else AuditCheck
                identity = sha256(f"{scenario[:1]}|{stage}|{system}|{user}".encode("utf-8")).hexdigest()
                # B reutiliza la llamada de A; D reutiliza la de C. No se vuelve a pagar.
                donor = {"B": "A", "D": "C"}.get(scenario)
                donor_key = None
                if donor:
                    donor_key = sha256(f"{donor}|{stage}|{system}|{user}".encode("utf-8")).hexdigest()
                key = identity
                label = f"{scenario}:{case['event_id'][:8]}:{stage}"
                if reuse and donor_key in seen:
                    rows.append({**seen[donor_key], "scenario": scenario, "label": label, "reused": True, "incurred_usd": "0"})
                    continue
                if not reuse and key in seen and scenario in {"A", "C"}:
                    pass
                provider = _provider_for(scenario, "verification" if stage == "verification" else "audit")
                before = budget.spent
                try:
                    parsed = provider.generate_structured(system_prompt=system, user_prompt=user, schema=schema)
                except CallBudgetExceeded as exc:
                    skipped.append({"label": label, "reason": str(exc)})
                    continue
                except Exception as exc:
                    skipped.append({"label": label, "reason": type(exc).__name__})
                    continue
                spent = budget.spent - before
                record = {
                    "scenario": scenario,
                    "label": label,
                    "event_id": case["event_id"],
                    "stage": stage,
                    "reused": False,
                    "model": getattr(provider, "model", None),
                    "thinking": getattr(provider, "thinking", None),
                    "incurred_usd": str(spent),
                    "result": parsed.model_dump(),
                }
                seen[key] = record
                rows.append(record)
                if not reuse:
                    try:
                        again = provider.generate_structured(system_prompt=system, user_prompt=user, schema=schema)
                    except CallBudgetExceeded as exc:
                        skipped.append({"label": label + ":pass2", "reason": str(exc)})
                        continue
                    except Exception as exc:
                        skipped.append({"label": label + ":pass2", "reason": type(exc).__name__})
                        continue
                    spent2 = budget.spent - before - spent
                    rows.append({**record, "label": label + ":pass2", "incurred_usd": str(spent2), "result": again.model_dump(), "pass": 2})
    report = {
        "budget_usd": str(BUDGET),
        "spent_usd": str(budget.spent),
        "held_usd": str(budget.held),
        "database": current,
        "calls": rows,
        "skipped": skipped,
        "note": (
            "Gasto incurrido de este ensayo, no el libro histórico. "
            "B y D no repiten la llamada de A y C. Los pases 2 de A y C sí se pagan. "
            "No se llamó a Exa, Replicate ni a publicación."
        ),
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("spent", report["spent_usd"], "calls", len(rows), "skipped", len(skipped))


if __name__ == "__main__":
    main()
