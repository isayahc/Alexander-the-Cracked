"""Shared fixtures for the Obvious MCP bridge tests.

MCP_BRIDGE_TOKEN is set before the server module is imported, because the module
creates the default ASGI app at import time. No test ever runs the real obvious
CLI: the run_cli wrapper is monkeypatched with a fake runner.
"""

from __future__ import annotations

import dataclasses
import os
from collections.abc import Callable
from typing import Any

os.environ.setdefault("MCP_BRIDGE_TOKEN", "test-token-not-a-secret")

import pytest
from starlette.testclient import TestClient

from obvious_mcp_bridge import server
from obvious_mcp_bridge.runner import CliError

TEST_TOKEN = "test-token-not-a-secret"


@dataclasses.dataclass
class CliInvocation:
    args: list[str]
    stdin_text: str | None
    kwargs: dict[str, Any]


class FakeCli:
    """Configurable stand-in for runner.run_cli: records argv, returns/raises."""

    def __init__(
        self,
        result: dict[str, Any] | None = None,
        error: CliError | None = None,
    ) -> None:
        self.invocations: list[CliInvocation] = []
        self._result = {} if result is None else result
        self._error = error

    def __call__(
        self,
        args: list[str],
        *,
        stdin_text: str | None = None,
        timeout: int = 60,
        cwd: str = "/home/user/project",
    ) -> dict[str, Any]:
        self.invocations.append(CliInvocation(args, stdin_text, {"timeout": timeout, "cwd": cwd}))
        if self._error is not None:
            raise self._error
        return self._result

    @property
    def last(self) -> CliInvocation:
        assert self.invocations, "expected at least one CLI invocation"
        return self.invocations[-1]


@pytest.fixture
def fake_cli(monkeypatch: pytest.MonkeyPatch) -> FakeCli:
    fake = FakeCli()
    monkeypatch.setattr(server, "run_cli", fake)
    return fake


@pytest.fixture
def failing_cli(monkeypatch: pytest.MonkeyPatch) -> Callable[[CliError], FakeCli]:
    def install(error: CliError) -> FakeCli:
        fake = FakeCli(error=error)
        monkeypatch.setattr(server, "run_cli", fake)
        return fake

    return install


@pytest.fixture
def app():
    return server.create_app(token=TEST_TOKEN)


@pytest.fixture
def client(app) -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


def mcp_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TEST_TOKEN}"}


def post_rpc(client: TestClient, payload: dict[str, Any]) -> Any:
    response = client.post("/mcp", json=payload, headers=mcp_headers())
    assert response.status_code == 200, response.text
    return response.json()
