from enum import StrEnum

from app.core.config import get_settings
from app.core.usage_context import bind_model_role
from app.providers.base import (
    EmbeddingProvider,
    ProviderNotConfiguredError,
    SearchProvider,
    StructuredLLMProvider,
)
from app.providers.openai_provider import OpenAIEmbeddingProvider, OpenAIStructuredProvider
from app.providers.voyage_provider import VoyageEmbeddingProvider


class ModelRole(StrEnum):
    ULTRA_LIGHT_PROCESSING = "ultra_light_processing"
    LIGHT_PROCESSING = "light_processing"
    AMBIGUOUS_DEDUP = "ambiguous_dedup"
    CLAIM_RESOLUTION = "claim_resolution"
    CLAIM_RESOLUTION_ESCALATED = "claim_resolution_escalated"
    VERIFICATION = "verification"
    WRITING = "writing"
    AUDITING = "auditing"
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


def _structured_role_config(role: ModelRole) -> tuple[str | None, str | None]:
    settings = get_settings()
    mapping = {
        ModelRole.ULTRA_LIGHT_PROCESSING: (
            settings.ultra_light_processing_provider,
            settings.ultra_light_processing_model,
        ),
        ModelRole.LIGHT_PROCESSING: (
            settings.light_processing_provider,
            settings.light_processing_model,
        ),
        ModelRole.AMBIGUOUS_DEDUP: (
            settings.ambiguous_dedup_provider,
            settings.ambiguous_dedup_model,
        ),
        ModelRole.CLAIM_RESOLUTION: (
            settings.claim_resolution_provider,
            settings.claim_resolution_model,
        ),
        ModelRole.CLAIM_RESOLUTION_ESCALATED: (
            settings.claim_resolution_escalated_provider,
            settings.claim_resolution_escalated_model,
        ),
        ModelRole.VERIFICATION: (
            settings.verification_provider,
            settings.verification_model,
        ),
        ModelRole.WRITING: (settings.writing_provider, settings.writing_model),
        ModelRole.AUDITING: (settings.auditing_provider, settings.auditing_model),
    }
    if role not in mapping:
        raise ProviderNotConfiguredError(f"El rol {role} no es un LLM estructurado")
    return mapping[role]


def get_structured_provider(role: ModelRole) -> StructuredLLMProvider:
    settings = get_settings()
    provider_name, model = _structured_role_config(role)

    if not provider_name or not model:
        raise ProviderNotConfiguredError(
            f"Falta {role.value} provider/model en el entorno"
        )
    if role == ModelRole.AUDITING and provider_name.lower() == "anthropic":
        raise ProviderNotConfiguredError("Anthropic no es un proveedor de auditoría")
    api_key = _api_key_for(provider_name)
    if not api_key:
        raise ProviderNotConfiguredError(
            f"Falta API key para el proveedor {provider_name} (rol {role.value})"
        )
    bind_model_role(role.value, provider=provider_name.lower())
    if provider_name.lower() == "openai":
        return OpenAIStructuredProvider(
            api_key=api_key, model=model, provider_name="openai"
        )
    if provider_name.lower() == "deepseek":
        return OpenAIStructuredProvider(
            api_key=api_key,
            model=model,
            base_url="https://api.deepseek.com",
            provider_name="deepseek",
        )
    if provider_name.lower() == "anthropic":
        from app.providers.anthropic_provider import AnthropicJsonProvider

        max_tokens = (
            settings.writing_max_output_tokens if role == ModelRole.WRITING else 4096
        )
        return AnthropicJsonProvider(
            api_key=api_key,
            model=model,
            max_output_tokens=max_tokens,
        )
    raise ProviderNotConfiguredError(
        f"Proveedor LLM no soportado todavía: {provider_name}"
    )


def get_structured_provider_optional(role: ModelRole) -> StructuredLLMProvider | None:
    """None si el rol no está configurado; no tapa otros errores."""
    try:
        return get_structured_provider(role)
    except ProviderNotConfiguredError:
        return None


def get_claim_resolution_provider(*, escalated: bool = False) -> StructuredLLMProvider:
    if not escalated:
        return get_structured_provider(ModelRole.CLAIM_RESOLUTION)
    try:
        return get_structured_provider(ModelRole.CLAIM_RESOLUTION_ESCALATED)
    except ProviderNotConfiguredError:
        return get_structured_provider(ModelRole.CLAIM_RESOLUTION)


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
    bind_model_role(ModelRole.EMBEDDING.value, provider=provider_name.lower())
    if provider_name.lower() == "voyage":
        return VoyageEmbeddingProvider(api_key=api_key, model=model)
    if provider_name.lower() == "openai":
        return OpenAIEmbeddingProvider(
            api_key=api_key, model=model, provider_name="openai"
        )
    raise ProviderNotConfiguredError(
        f"Proveedor de embeddings no soportado todavía: {provider_name}"
    )


def get_search_provider() -> SearchProvider:
    settings = get_settings()
    provider_name = (settings.search_provider or "").strip().lower()
    if not provider_name:
        raise ProviderNotConfiguredError("Falta SEARCH_PROVIDER")
    if provider_name == "brave":
        if not settings.brave_api_key:
            raise ProviderNotConfiguredError("Falta BRAVE_API_KEY")
        from app.providers.brave import BraveSearchProvider

        return BraveSearchProvider(api_key=settings.brave_api_key)
    if provider_name == "exa":
        if not settings.exa_api_key:
            raise ProviderNotConfiguredError("Falta EXA_API_KEY")
        from app.providers.exa import ExaSearchProvider

        return ExaSearchProvider(api_key=settings.exa_api_key)
    raise ProviderNotConfiguredError(
        f"Proveedor de búsqueda no soportado todavía: {provider_name}"
    )
