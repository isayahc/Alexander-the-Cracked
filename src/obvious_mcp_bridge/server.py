"""The Obvious MCP bridge server: FastMCP over Streamable HTTP with bearer auth.

Four tools shell out to the obvious CLI and return its parsed JSON. The bearer
token comes from the MCP_BRIDGE_TOKEN env var (startup fails fast when unset)
and is compared in constant time; it is never logged.
"""

from __future__ import annotations

import hmac
import os

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from obvious_mcp_bridge.runner import CliError, run_cli

SERVER_NAME = "obvious-bridge"
TOKEN_ENV_VAR = "MCP_BRIDGE_TOKEN"
MCP_PATH = "/mcp"
HEALTHZ_PATH = "/healthz"


def _bearer_token() -> str:
    token = os.environ.get(TOKEN_ENV_VAR, "")
    if not token:
        raise RuntimeError(
            f"Refusing to start: {TOKEN_ENV_VAR} is not set. "
            "Generate a strong random value and store it as an Obvious secret."
        )
    return token


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Constant-time bearer-token check; /healthz stays open, everything else 401s."""

    def __init__(self, app, token: str) -> None:
        super().__init__(app)
        self._token = token

    async def dispatch(self, request: Request, call_next):
        if request.url.path == HEALTHZ_PATH:
            return await call_next(request)
        header = request.headers.get("authorization", "")
        supplied = header[len("Bearer "):] if header.startswith("Bearer ") else ""
        if supplied and hmac.compare_digest(supplied, self._token):
            return await call_next(request)
        return JSONResponse({"error": "unauthorized"}, status_code=401)


def _tool_call(args: list[str], stdin_text: str | None = None) -> dict:
    try:
        return run_cli(args, stdin_text=stdin_text)
    except CliError as exc:
        raise ToolError(f"obvious CLI {exc.kind}: {exc.message}") from exc


def create_mcp() -> FastMCP:
    """Build the FastMCP instance with its tools and the health route."""
    mcp = FastMCP(name=SERVER_NAME)

    @mcp.custom_route(HEALTHZ_PATH, methods=["GET"])
    async def healthz(request: Request) -> JSONResponse:
        return JSONResponse({"ok": True})

    for tool in (list_tasks, create_task, update_task, create_document):
        mcp.tool(tool)

    return mcp


def list_tasks(status: str = "") -> dict:
    """List tasks in the Obvious project, optionally filtered by status.

    Read-only view of work in flight (mirrors `obvious tasks list`).
    Pass status like 'in_progress', 'waiting', or 'completed' to filter;
    leave empty for all tasks.
    """
    args = ["tasks", "list"]
    if status:
        args.append(f"--status={status}")
    return _tool_call(args)


def create_task(title: str, description: str = "", assignee: str = "") -> dict:
    """Create a task in the Obvious project.

    Returns the created task record. Optionally set a description and an
    assignee to route the work to a specific agent or worker.
    """
    args = ["tasks", "create", f"--title={title}"]
    if description:
        args.append(f"--description={description}")
    if assignee:
        args.append(f"--assignee={assignee}")
    return _tool_call(args)


def update_task(task_id: str, status: str = "", completion_note: str = "") -> dict:
    """Update an Obvious task: move its status and/or record a completion note.

    Pass the task id (e.g. 'todo_abc123') plus a new status ('in_progress',
    'waiting', 'completed', ...) and/or a completion_note describing the
    outcome. At least one of status or completion_note is required.
    """
    if not status and not completion_note:
        raise ToolError("update_task requires status and/or completion_note")
    args = ["tasks", "update", f"--taskId={task_id}"]
    if status:
        args.append(f"--status={status}")
    if completion_note:
        args.append(f"--completionNote={completion_note}")
    return _tool_call(args)


def create_document(name: str, markdown: str, description: str = "") -> dict:
    """Publish a markdown document artifact into the Obvious project.

    'name' is the document title, 'markdown' the full document body.
    Returns the created artifact record.
    """
    args = ["artifacts", "create", "--type=document", f"--name={name}"]
    if description:
        args.append(f"--description={description}")
    return _tool_call(args, stdin_text=markdown)


def create_app(token: str | None = None):
    """Build the ASGI app: MCP at /mcp, open health at /healthz, bearer auth between."""
    token = token if token is not None else _bearer_token()
    mcp = create_mcp()
    return mcp.http_app(
        path=MCP_PATH,
        stateless_http=True,
        json_response=True,
        middleware=[Middleware(BearerAuthMiddleware, token=token)],
    )


app = create_app()
