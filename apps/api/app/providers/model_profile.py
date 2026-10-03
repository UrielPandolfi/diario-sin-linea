"""Perfil de modelos. current usa el entorno; candidate reemplaza roles puntuales."""

from __future__ import annotations

from app.core.config import get_settings

# Extracción de claims (light), redacción, embeddings e imagen no están acá.
CANDIDATE_ASSIGNMENTS: dict[str, tuple[str, str]] = {
    "ultra_light_processing": ("deepseek", "deepseek-flash"),
    "ambiguous_dedup": ("deepseek", "deepseek-flash"),
    "claim_resolution": ("deepseek", "deepseek-flash"),
    "claim_resolution_escalated": ("deepseek", "deepseek-flash"),
    "verification": ("deepseek", "deepseek-v4-pro"),
    "auditing": ("deepseek", "deepseek-flash"),
    "image_prompt": ("deepseek", "deepseek-flash"),
}


def candidate_roles() -> set[str]:
    settings = get_settings()
    raw = (settings.cost_profile_roles or "").strip()
    if not raw:
        return set(CANDIDATE_ASSIGNMENTS)
    return {part.strip() for part in raw.split(",") if part.strip()}


def profile_for(role: str) -> tuple[str | None, str | None, str | None]:
    """Proveedor, modelo y thinking solicitado. thinking es None o 'disabled'."""
    settings = get_settings()
    if (settings.cost_profile or "").strip().lower() != "candidate":
        return None, None, None
    if role not in candidate_roles():
        return None, None, None
    assignment = CANDIDATE_ASSIGNMENTS.get(role)
    if assignment is None:
        return None, None, None
    provider, model = assignment
    thinking = "disabled" if provider == "deepseek" else None
    return provider, model, thinking
