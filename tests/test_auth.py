"""Tests for the X-API-Key dependency in app/auth.py."""

import hmac

from app.auth import generate_api_key


def test_chat_rejects_missing_key(client):
    assert client.post("/chat", json={"session_id": "s1", "message": "hi"}).status_code == 401


def test_chat_rejects_wrong_key(client):
    resp = client.post(
        "/chat",
        json={"session_id": "s1", "message": "hi"},
        headers={"X-API-Key": "wrong"},
    )
    assert resp.status_code == 401


def test_chat_rejects_key_when_server_key_unset(monkeypatch, settings_env):
    monkeypatch.delenv("APP_API_KEY")
    from app.config import get_settings

    get_settings.cache_clear()
    from fastapi.testclient import TestClient

    from app.main import app

    resp = TestClient(app).post(
        "/chat",
        json={"session_id": "s1", "message": "hi"},
        headers={"X-API-Key": "anything"},
    )
    assert resp.status_code == 503


def test_health_is_open(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_generate_api_key_is_long_random():
    k1, k2 = generate_api_key(), generate_api_key()
    assert len(k1) == 64 and k1 != k2
    assert hmac.compare_digest(k1, k1)
