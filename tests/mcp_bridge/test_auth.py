"""Bearer auth middleware tests: 401 paths, passthrough, health exemption, no leaks."""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from obvious_mcp_bridge import server

from .conftest import TEST_TOKEN, mcp_headers


def test_missing_token_is_401(client: TestClient) -> None:
    response = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert response.status_code == 401
    assert response.json() == {"error": "unauthorized"}


def test_wrong_token_is_401(client: TestClient) -> None:
    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert response.status_code == 401


def test_non_bearer_header_is_401(client: TestClient) -> None:
    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
        headers={"Authorization": f"Basic {TEST_TOKEN}"},
    )
    assert response.status_code == 401


def test_correct_token_passes_through(client: TestClient, fake_cli) -> None:
    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
        headers=mcp_headers(),
    )
    assert response.status_code == 200


def test_healthz_open_without_auth(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_healthz_open_even_with_bad_token(client: TestClient) -> None:
    response = client.get("/healthz", headers={"Authorization": "Bearer garbage"})
    assert response.status_code == 200


def test_token_never_appears_in_logs(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("DEBUG"):
        client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
            headers={"Authorization": f"Bearer {TEST_TOKEN}"},
        )
        client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 2, "method": "ping"},
            headers={"Authorization": f"Bearer {TEST_TOKEN}-nope"},
        )
    assert TEST_TOKEN not in caplog.text
    assert "wrong-token" not in caplog.text


def test_startup_fails_fast_without_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(server.TOKEN_ENV_VAR, raising=False)
    with pytest.raises(RuntimeError, match="MCP_BRIDGE_TOKEN is not set"):
        server.create_app()
