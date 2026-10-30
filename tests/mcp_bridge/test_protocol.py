"""Protocol smoke over the real ASGI app: initialize, tools/list, tools/call."""

from __future__ import annotations

from starlette.testclient import TestClient

from .conftest import FakeCli, mcp_headers, post_rpc

EXPECTED_TOOLS = {"list_tasks", "create_task", "update_task", "create_document"}

INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "pytest", "version": "0.0.0"},
    },
}


def test_initialize_and_tools_list(client: TestClient) -> None:
    result = post_rpc(client, INITIALIZE)["result"]
    assert "protocolVersion" in result
    assert result["serverInfo"]["name"] == "obvious-bridge"

    notified = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        },
        headers=mcp_headers(),
    )
    assert notified.status_code in (200, 202, 204)

    listing = post_rpc(
        client,
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    )
    tool_names = {tool["name"] for tool in listing["result"]["tools"]}
    assert tool_names == EXPECTED_TOOLS


def test_tools_call_round_trip(
    client: TestClient, monkeypatch, fake_cli: FakeCli
) -> None:
    fake_cli._result = {"tasks": [{"id": "todo_7", "title": "from MCP"}]}
    call = post_rpc(
        client,
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "list_tasks", "arguments": {"status": ""}},
        },
    )
    assert "error" not in call, call
    content = call["result"]["content"]
    assert content, call
    text = content[0]["text"]
    assert "todo_7" in text
    assert fake_cli.last.args == ["tasks", "list"]


def test_tools_call_reports_cli_failure_as_tool_error(
    client: TestClient, failing_cli
) -> None:
    from obvious_mcp_bridge.runner import CliError

    failing_cli(CliError("cli_failed", "boom from the CLI"))
    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "list_tasks", "arguments": {}},
        },
        headers=mcp_headers(),
    )
    body = response.json()
    assert body["result"]["isError"] is True
    assert "boom from the CLI" in body["result"]["content"][0]["text"]
