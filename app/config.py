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

    # This API's own key (not an Azure credential)
    app_api_key: str = ""

    # Guardrails
    max_message_length: int = Field(default=4000, gt=0)
    rate_limit_per_minute: int = Field(default=30, gt=0)

    # Embeddings (used by ingest to vectorize chunks)
    embedding_model_deployment: str = "text-embedding-3-large"
    embedding_dimensions: int = Field(default=3072, gt=0)

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

    def missing_for_api(self) -> list[str]:
        """Settings required to serve /chat. Empty means 'not configured'."""
        required = {
            "azure_ai_project_endpoint": self.azure_ai_project_endpoint,
            "azure_search_endpoint": self.azure_search_endpoint,
            "azure_search_connection_name": self.azure_search_connection_name,
            "app_api_key": self.app_api_key,
        }
        return [name for name, value in required.items() if not value]


@lru_cache
def get_settings() -> Settings:
    """Cached settings so .env is parsed once per process."""
    return Settings()
