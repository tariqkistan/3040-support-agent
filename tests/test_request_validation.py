"""Tests for /chat request validation."""

HEADERS = {"X-API-Key": "test-secret-key"}


def _stub_agent(monkeypatch):
    async def fake_run(session_id, message, settings):
        return "stub answer", [{"section": "Intro", "page": 1}]

    monkeypatch.setattr("app.agent.run_agent_turn", fake_run)
    # Ensure the deferred import inside chat() picks up the stub
    import app.agent  # noqa: F401


def test_empty_message_rejected(client):
    resp = client.post("/chat", json={"session_id": "s", "message": ""}, headers=HEADERS)
    assert resp.status_code == 422


def test_missing_session_id_rejected(client):
    resp = client.post("/chat", json={"message": "hi"}, headers=HEADERS)
    assert resp.status_code == 422


def test_oversized_message_rejected(client, settings_env, monkeypatch):
    _stub_agent(monkeypatch)
    monkeypatch.setenv("MAX_MESSAGE_LENGTH", "10")
    from app.config import get_settings

    get_settings.cache_clear()
    resp = client.post(
        "/chat",
        json={"session_id": "s", "message": "x" * 11},
        headers=HEADERS,
    )
    assert resp.status_code == 422


def test_valid_request_returns_answer(client, monkeypatch):
    _stub_agent(monkeypatch)
    resp = client.post(
        "/chat",
        json={"session_id": "s", "message": "How do I reset the device?"},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"] == "stub answer"
    assert body["sources"] == [{"section": "Intro", "page": 1}]


def test_openapi_has_operation_ids_and_security(client):
    spec = client.get("/openapi.json").json()
    assert spec["paths"]["/chat"]["post"]["operationId"] == "chatWithSupportAgent"
    assert spec["paths"]["/health"]["get"]["operationId"] == "healthCheck"
    assert "ApiKeyAuth" in spec["components"]["securitySchemes"] or any(
        scheme.get("type") == "apiKey"
        for scheme in spec["components"]["securitySchemes"].values()
    )
