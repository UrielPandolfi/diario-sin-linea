from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    database_url: str = (
        "postgresql+psycopg://sin_linea:sin_linea@localhost:5432/sin_linea"
    )
    redis_url: str = "redis://localhost:6379/0"
    app_secret: str = "dev-secret-change-me"
    admin_password: str = "dev-admin"
    cors_origins: str = "http://localhost:3000"

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
    ingestion_poll_interval_seconds: int = 900
    # 0 = unlimited. >0 caps new sucesos (and initial detection batch) per poll.
    max_new_events_per_poll: int = 0
    feed_relevance_weight: float = 1.0
    feed_freshness_weight: float = 1.0
    feed_locality_weight: float = 1.0
    nearby_window_hours: int = 12
    trusted_proxies: str = ""

    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    def trusted_proxy_list(self) -> list[str]:
        return [item.strip() for item in self.trusted_proxies.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
