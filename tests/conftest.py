import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app


@pytest.fixture()
def settings_env(monkeypatch):
    """Point settings at a known-good test configuration."""
    env = {
        "AZURE_AI_PROJECT_ENDPOINT": "https://example.services.ai.azure.com/api/projects/p/",
        "AZURE_SEARCH_ENDPOINT": "https://example.search.windows.net/",
        "AZURE_SEARCH_CONNECTION_NAME": "my-search-conn",
        "APP_API_KEY": "test-secret-key",
        "AGENT_MODEL_DEPLOYMENT": "gpt-4o",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    yield env
    get_settings.cache_clear()


@pytest.fixture()
def client(settings_env):
    return TestClient(app)
