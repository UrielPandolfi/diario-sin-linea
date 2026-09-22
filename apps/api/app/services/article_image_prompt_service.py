from __future__ import annotations

from pydantic import BaseModel

from app.core.prompts import load_prompt
from app.providers.base import ProviderNotConfiguredError
from app.providers.registry import ModelRole, get_structured_provider
from app.services.hero_image_error import HeroImageError

_PROMPT_FILE = "article_image_prompt.md"


class GeneratedImagePrompt(BaseModel):
    prompt: str


class ArticleImagePromptService:
    def __init__(self, llm=None) -> None:
        self.llm = llm

    def generate(self, *, headline: str, summary: str) -> str:
        title = (headline or "").strip()
        deck = (summary or "").strip()
        if not title or not deck:
            raise HeroImageError(
                "missing_text",
                "El artículo no tiene titular o bajada",
                422,
            )
        try:
            llm = self.llm or get_structured_provider(ModelRole.IMAGE_PROMPT)
            result = llm.generate_structured(
                system_prompt=load_prompt(_PROMPT_FILE),
                user_prompt=f"Headline:\n{title}\n\nSummary:\n{deck}",
                schema=GeneratedImagePrompt,
            )
        except HeroImageError:
            raise
        except ProviderNotConfiguredError as exc:
            raise HeroImageError(
                "missing_image_prompt_config",
                "Falta la configuración de DeepSeek para el prompt de imagen",
                503,
            ) from exc
        except Exception as exc:
            raise HeroImageError(
                "image_prompt_error",
                "No se pudo generar el prompt de imagen",
                502,
            ) from exc
        prompt = (result.prompt or "").strip()
        if not prompt:
            raise HeroImageError(
                "empty_prompt",
                "El modelo no devolvió un prompt",
                502,
            )
        return prompt
