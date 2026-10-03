from functools import lru_cache

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_PSYCOPG2_DEFAULT_PREFIXES = (
    "postgres://",
    "postgresql://",
)


def normalize_database_url(url: str) -> str:
    """Map libpq URLs to SQLAlchemy's psycopg v3 dialect.

    Railway/Heroku expose postgres:// or postgresql://. SQLAlchemy treats those
    as postgresql+psycopg2, which this project does not install.
    """
    stripped = url.strip()
    for prefix in _PSYCOPG2_DEFAULT_PREFIXES:
        if stripped.startswith(prefix):
            return "postgresql+psycopg://" + stripped[len(prefix) :]
    return stripped


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    database_url: str = (
        "postgresql+psycopg://sin_linea:sin_linea@localhost:5432/sin_linea"
    )
    # Pytest only. Absence must abort the suite; never a fallback for database_url.
    test_database_url: str | None = None

    @field_validator("database_url", mode="before")
    @classmethod
    def coerce_psycopg3_database_url(cls, value: object) -> object:
        if isinstance(value, str):
            return normalize_database_url(value)
        return value

    @field_validator("test_database_url", mode="before")
    @classmethod
    def coerce_psycopg3_test_database_url(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return None
            return normalize_database_url(stripped)
        return value

    redis_url: str = "redis://localhost:6379/0"
    app_secret: str = "dev-secret-change-me"
    # Sin default de desarrollo: el arranque lo rechaza vacío o si sigue siendo un valor conocido.
    admin_password: str = ""
    cors_origins: str = "http://localhost:3000"
    site_url: str = "http://localhost:3000"
    cookie_secure: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_tls: bool = True

    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    deepseek_api_key: str | None = None
    voyage_api_key: str | None = None
    brave_api_key: str | None = None
    exa_api_key: str | None = None

    light_processing_provider: str | None = None
    light_processing_model: str | None = None
    ultra_light_processing_provider: str | None = None
    ultra_light_processing_model: str | None = None
    ambiguous_dedup_provider: str | None = None
    ambiguous_dedup_model: str | None = None
    claim_resolution_provider: str | None = None
    claim_resolution_model: str | None = None
    claim_resolution_escalated_provider: str | None = None
    claim_resolution_escalated_model: str | None = None
    claim_resolution_escalate_confidence: float = 0.55
    verification_provider: str | None = None
    verification_model: str | None = None
    writing_provider: str | None = None
    writing_model: str | None = None
    writing_reasoning_effort: str | None = None
    auditing_provider: str | None = None
    auditing_model: str | None = None
    embedding_provider: str | None = None
    embedding_model: str | None = None
    search_provider: str | None = None
    image_prompt_provider: str | None = None
    image_prompt_model: str | None = None
    replicate_api_token: str | None = None
    article_image_enabled: bool = True
    article_image_model: str = "black-forest-labs/flux-schnell"
    article_image_aspect_ratio: str = "16:9"
    article_image_output_format: str = "webp"
    article_image_output_quality: int = 80
    article_image_num_inference_steps: int = 4
    article_image_megapixels: str = "1"
    article_image_go_fast: bool = True

    # current conserva los modelos del entorno. candidate cambia solo los roles listados.
    # Lista vacía con candidate = todos los roles del perfil candidato.
    cost_profile: str = "current"
    cost_profile_roles: str = ""
    usage_environment: str = "production"
    # 2 h: cubre un poll, sus reintentos y un segundo pase del mismo ciclo,
    # y vence antes de que el día siguiente reemplace las fuentes.
    search_cache_enabled: bool = False
    search_cache_ttl_seconds: int = 7200
    # 6 h: la identidad ya incluye evidencia y procedencia; el TTL cubre
    # el caso en que el mundo se movió sin un documento nuevo. No es indefinido.
    verification_reuse_enabled: bool = False
    verification_reuse_ttl_seconds: int = 21600
    # Tope de gasto estimado por proceso. Vacío = sin tope.
    cost_call_budget_usd: float | None = None

    auto_publish: bool = False
    initial_research_queries: int = 2
    max_research_queries_per_event: int = 4
    max_research_results_per_query: int = 5
    max_research_results_per_domain: int = 3
    max_standard_event_sources: int = 4
    max_escalated_event_sources: int = 8
    max_verification_claims_per_event: int = 5
    max_verification_queries_per_claim: int = 3
    max_verification_results_per_query: int = 3
    max_writing_claims_per_event: int = 40
    max_writing_sources_per_event: int = 20
    max_writing_source_contexts: int = 6
    writing_source_context_chars: int = 5000
    writing_excerpt_chars: int = 400
    writing_max_output_tokens: int = 4096
    claim_extraction_source_chars: int = 5000
    editorial_country_code: str = "AR"
    max_audit_rewrite_cycles: int = 2
    job_max_retries: int = 3
    event_match_high_threshold: float = 0.88
    event_match_low_threshold: float = 0.72
    event_match_window_hours: int = 72
    embedding_dimensions: int = 1024
    monitored_source_poll_limit: int = 5
    monitored_source_poll_interval_seconds: int = Field(
        default=300,
        validation_alias=AliasChoices(
            "MONITORED_SOURCE_POLL_INTERVAL_SECONDS",
            "INGESTION_POLL_INTERVAL_SECONDS",
        ),
    )
    # 0 = unlimited. >0 caps new sucesos (and initial detection batch) per poll.
    max_new_events_per_poll: int = 0
    feed_relevance_weight: float = 1.0
    feed_freshness_weight: float = 1.0
    feed_locality_weight: float = 1.0
    # Principal. The three weights above stay on the legacy scope ranking used by /local.
    feed_principal_relevance_weight: float = 0.45
    feed_principal_freshness_weight: float = 0.35
    feed_principal_locality_weight: float = 0.20
    feed_affinity_boost: float = 0.15
    feed_affinity_confidence_events: int = 5
    feed_signal_window_days: int = 30
    feed_read_weight: float = 1.0
    feed_like_weight: float = 3.0
    feed_freshness_halflife_hours: float = 24.0
    feed_missing_relevance: float = 0.5
    feed_cursor_max_age_seconds: int = 3600
    nearby_window_hours: int = 12
    trusted_proxies: str = ""

    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    def trusted_proxy_list(self) -> list[str]:
        return [item.strip() for item in self.trusted_proxies.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
