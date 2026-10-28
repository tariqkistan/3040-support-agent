"""Tests for /chat request validation."""

HEADERS = {"X-API-Key": "test-secret-key"}


def _stub_agent(monkeypatch):
    async def fake_run(caller_id, session_id, message, settings):
        assert caller_id
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


def test_valid_request_returns_answer(client, monkeypatch, caplog):
    import logging

    _stub_agent(monkeypatch)
    caplog.set_level(logging.INFO, logger="app.request")
    question = "How do I reset the device?"
    resp = client.post(
        "/chat",
        json={"session_id": "s", "message": question},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"] == "stub answer"
    assert body["session_id"] == "s"
    assert body["sources"] == [{"section": "Intro", "page": 1}]
    assert resp.headers["X-Request-ID"]
    assert question not in caplog.text
    assert "test-secret-key" not in caplog.text


def test_openapi_has_operation_ids_and_security(client):
    spec = client.get("/openapi.json").json()
    assert spec["paths"]["/chat"]["post"]["operationId"] == "chatWithSupportAgent"
    assert spec["paths"]["/health"]["get"]["operationId"] == "healthCheck"
    assert spec["paths"]["/ready"]["get"]["operationId"] == "readinessCheck"
    assert "ApiKeyAuth" in spec["components"]["securitySchemes"] or any(
        scheme.get("type") == "apiKey"
        for scheme in spec["components"]["securitySchemes"].values()
    )


def test_copilot_openapi_uses_swagger_2_and_exposes_chat(client):
    spec = client.get("/copilot-openapi.json").json()

    assert spec["swagger"] == "2.0"
    assert spec["paths"]["/chat"]["post"]["operationId"] == "chatWithSupportAgent"
    assert spec["securityDefinitions"]["ApiKeyHeader"] == {
        "type": "apiKey",
        "name": "X-API-Key",
        "in": "header",
    }
    assert spec["paths"]["/chat"]["post"]["parameters"][0]["in"] == "body"
    assert "#/components/schemas/" not in str(spec["definitions"])


def test_readiness_fails_when_configuration_is_missing(client, settings_env, monkeypatch):
    monkeypatch.delenv("AZURE_SEARCH_CONNECTION_NAME")
    from app.config import get_settings

    get_settings.cache_clear()
    resp = client.get("/ready")
    assert resp.status_code == 503
    assert "azure_search_connection_name" in resp.json()["missing_settings"]
