"""Web layer tests: the API contract judges will exercise."""

import pytest
from fastapi.testclient import TestClient

from app.web import create_app


@pytest.fixture
def client(demo_settings) -> TestClient:
    return TestClient(create_app(demo_settings))


def test_health_reports_demo_mode_and_planner(client: TestClient):
    payload = client.get("/health").json()
    assert payload["status"] == "ok"
    assert payload["mode"] == "demo"
    assert payload["planner"] == "local"


def test_index_serves_the_chat_ui(client: TestClient):
    response = client.get("/")
    assert response.status_code == 200
    assert "PayPilot" in response.text


def test_chat_create_order(client: TestClient):
    response = client.post(
        "/api/chat", json={"text": "create an order for $12.50 to Zed", "session_id": "t1"}
    )
    payload = response.json()
    assert response.status_code == 200
    assert payload["status"] == "executed"
    assert payload["mode"] == "demo"
    assert "Created order" in payload["message"]


def test_chat_confirmation_roundtrip(client: TestClient):
    first = client.post(
        "/api/chat",
        json={"text": "capture order DEMOORD0001", "session_id": "t2"},
    ).json()
    assert first["status"] == "needs_confirmation"

    second = client.post(
        "/api/chat", json={"text": "confirm", "session_id": "t2"}
    ).json()
    assert second["status"] == "error"  # demo ledger has no such order - honest failure
    assert "PayPal" in second["message"]


def test_chat_blocked_by_policy(client: TestClient):
    response = client.post(
        "/api/chat", json={"text": "create an order for $20000", "session_id": "t3"}
    )
    payload = response.json()
    assert payload["status"] == "blocked"
    assert "Blocked by policy" in payload["message"]


def test_sessions_are_independent(client: TestClient):
    client.post("/api/chat", json={"text": "capture order DEMOORD0001", "session_id": "a"})
    other = client.post("/api/chat", json={"text": "confirm", "session_id": "b"}).json()
    assert other["status"] == "answer"  # nothing pending in this session -> help
