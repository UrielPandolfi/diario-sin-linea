from enum import StrEnum

from app.core.config import get_settings
from app.providers.base import EmbeddingProvider, ProviderNotConfiguredError, StructuredLLMProvider
from app.providers.openai_provider import OpenAIEmbeddingProvider, OpenAIStructuredProvider
from app.providers.voyage_provider import VoyageEmbeddingProvider


class ModelRole(StrEnum):
    LIGHT_PROCESSING = "light_processing"
    AMBIGUOUS_DEDUP = "ambiguous_dedup"
    EMBEDDING = "embedding"


def _api_key_for(provider: str) -> str | None:
    settings = get_settings()
    mapping = {
        "openai": settings.openai_api_key,
        "anthropic": settings.anthropic_api_key,
        "deepseek": settings.deepseek_api_key,
        "voyage": settings.voyage_api_key,
    }
    return mapping.get(provider.lower())


def get_structured_provider(role: ModelRole) -> StructuredLLMProvider:
    settings = get_settings()
    if role == ModelRole.LIGHT_PROCESSING:
        provider_name = settings.light_processing_provider
        model = settings.light_processing_model
    elif role == ModelRole.AMBIGUOUS_DEDUP:
        provider_name = settings.ambiguous_dedup_provider
        model = settings.ambiguous_dedup_model
    else:
        raise ProviderNotConfiguredError(f"El rol {role} no es un LLM estructurado")

    if not provider_name or not model:
        raise ProviderNotConfiguredError(
            f"Falta {role.value} provider/model en el entorno"
        )
    api_key = _api_key_for(provider_name)
    if not api_key:
        raise ProviderNotConfiguredError(
            f"Falta API key para el proveedor {provider_name} (rol {role.value})"
        )
    if provider_name.lower() == "openai":
        return OpenAIStructuredProvider(api_key=api_key, model=model)
    raise ProviderNotConfiguredError(
        f"Proveedor LLM no soportado todavía: {provider_name}"
    )


def get_embedding_provider() -> EmbeddingProvider:
    settings = get_settings()
    provider_name = settings.embedding_provider
    model = settings.embedding_model
    if not provider_name or not model:
        raise ProviderNotConfiguredError("Falta EMBEDDING_PROVIDER o EMBEDDING_MODEL")
    api_key = _api_key_for(provider_name)
    if not api_key:
        raise ProviderNotConfiguredError(
            f"Falta API key para embeddings ({provider_name})"
        )
    if provider_name.lower() == "voyage":
        return VoyageEmbeddingProvider(api_key=api_key, model=model)
    if provider_name.lower() == "openai":
        return OpenAIEmbeddingProvider(api_key=api_key, model=model)
    raise ProviderNotConfiguredError(
        f"Proveedor de embeddings no soportado todavía: {provider_name}"
    )
