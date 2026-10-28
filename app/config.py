"""Environment-based settings for the support agent.

Everything the app needs comes from environment variables (or a local
.env file). No Azure keys are stored here or anywhere: Azure access uses
DefaultAzureCredential (Entra ID). The only secret is APP_API_KEY, which
protects this service's own HTTP endpoint.
"""

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables / .env."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Microsoft Foundry project
    azure_ai_project_endpoint: str = ""
    agent_model_deployment: str = "gpt-4o"

    # Azure AI Search
    azure_search_endpoint: str = ""
    azure_search_index: str = "support-docs"
    azure_search_connection_name: str = ""
    # 'vector_semantic_hybrid' needs a Search tier with semantic ranker (Basic+);
    # free tier uses 'vector_simple_hybrid'.
    search_query_type: str = "vector_simple_hybrid"

    # This API's own key (not an Azure credential)
    app_api_key: str = ""

    # Conversation mapping. Memory is for local development only; hosted
    # deployments should use Cosmos DB with item TTL enabled.
    session_store_backend: str = "memory"
    azure_cosmos_endpoint: str = ""
    azure_cosmos_database: str = "support-agent"
    azure_cosmos_container: str = "agent-sessions"
    session_ttl_seconds: int = Field(default=30 * 24 * 60 * 60, gt=0)

    # Guardrails
    max_message_length: int = Field(default=4000, gt=0)
    rate_limit_per_minute: int = Field(default=30, gt=0)

    # Embeddings (used by ingest to vectorize chunks). Custom deployments live on
    # the account's Azure OpenAI endpoint, not the project's /openai/v1 route.
    azure_openai_endpoint: str = ""
    embedding_model_deployment: str = "text-embedding-3-large"
    embedding_dimensions: int = Field(default=3072, gt=0)

    # LLM judge for evals — must be a non-reasoning chat model (azure-ai-evaluation
    # uses chat completions with max_tokens, which reasoning models reject).
    eval_model_deployment: str = "gpt-4.1-mini"

    # Optional: only needed when the source PDF is scanned
    document_intelligence_endpoint: str = ""

    @field_validator(
        "azure_ai_project_endpoint", "azure_search_endpoint", mode="before"
    )
    @classmethod
    def strip_trailing_slash(cls, v: object) -> object:
        if isinstance(v, str):
            return v.rstrip("/")
        return v

    @field_validator("session_store_backend", mode="before")
    @classmethod
    def normalize_session_store_backend(cls, v: object) -> object:
        if isinstance(v, str):
            v = v.strip().lower()
            if v not in {"memory", "cosmos"}:
                raise ValueError("SESSION_STORE_BACKEND must be 'memory' or 'cosmos'.")
        return v

    def missing_for_api(self) -> list[str]:
        """Settings required to serve /chat. Empty means 'not configured'."""
        required = {
            "azure_ai_project_endpoint": self.azure_ai_project_endpoint,
            "azure_search_endpoint": self.azure_search_endpoint,
            "azure_search_connection_name": self.azure_search_connection_name,
            "app_api_key": self.app_api_key,
        }
        if self.session_store_backend == "cosmos":
            required["azure_cosmos_endpoint"] = self.azure_cosmos_endpoint
        return [name for name, value in required.items() if not value]


@lru_cache
def get_settings() -> Settings:
    """Cached settings so .env is parsed once per process."""
    return Settings()
