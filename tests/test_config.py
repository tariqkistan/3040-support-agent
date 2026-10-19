"""Tests for app/config.py settings parsing."""

import pytest

from app.config import Settings, get_settings


def test_defaults():
    s = Settings(app_api_key="k")
    assert s.max_message_length == 4000
    assert s.rate_limit_per_minute == 30
    assert s.azure_search_index == "support-docs"


def test_trailing_slash_stripped():
    s = Settings(
        app_api_key="k",
        azure_ai_project_endpoint="https://x.example.com/",
        azure_search_endpoint="https://y.search.windows.net/",
    )
    assert s.azure_ai_project_endpoint == "https://x.example.com"
    assert s.azure_search_endpoint == "https://y.search.windows.net"


def test_missing_for_api_lists_empty_fields():
    s = Settings(_env_file=None)
    assert set(s.missing_for_api()) == {
        "azure_ai_project_endpoint",
        "azure_search_endpoint",
        "azure_search_connection_name",
        "app_api_key",
    }
    full = Settings(
        app_api_key="k",
        azure_ai_project_endpoint="https://x",
        azure_search_endpoint="https://y",
        azure_search_connection_name="c",
    )
    assert full.missing_for_api() == []


def test_env_loading(monkeypatch):
    monkeypatch.setenv("APP_API_KEY", "from-env")
    monkeypatch.setenv("MAX_MESSAGE_LENGTH", "100")
    get_settings.cache_clear()
    s = get_settings()
    assert s.app_api_key == "from-env"
    assert s.max_message_length == 100
    get_settings.cache_clear()


def test_invalid_limits_rejected():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(app_api_key="k", rate_limit_per_minute=0)
