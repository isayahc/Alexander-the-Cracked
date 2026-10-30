"""Subprocess wrapper around the obvious CLI used by every bridge tool.

Tests never execute the real CLI: tools call this wrapper, and tests monkeypatch
it. Here, and only here, subprocess execution lives.
"""

from __future__ import annotations

import json
import os
import subprocess

CLI_NAME = "obvious"
CLI_TIMEOUT_SECONDS = 60

# The project sandbox home is where the obvious CLI resolves the workspace
# context from; override with OBVIOUS_BRIDGE_CWD if the deployment differs.
DEFAULT_CWD = os.environ.get("OBVIOUS_BRIDGE_CWD", "/home/user/project")

_EXCERPT_LIMIT = 400


def _excerpt(text: str, limit: int = _EXCERPT_LIMIT) -> str:
    return text.strip()[:limit]


class CliError(Exception):
    """Typed failure from the obvious CLI subprocess.

    ``kind`` distinguishes the failure modes (``cli_failed``, ``invalid_output``,
    ``timeout``, ``cli_missing``); ``message`` carries a caller-safe excerpt.
    """

    def __init__(self, kind: str, message: str) -> None:
        self.kind = kind
        self.message = message
        super().__init__(f"{kind}: {message}")


def run_cli(
    args: list[str],
    *,
    stdin_text: str | None = None,
    timeout: int = CLI_TIMEOUT_SECONDS,
    cwd: str = DEFAULT_CWD,
) -> dict:
    """Run the obvious CLI and return its parsed JSON stdout.

    Raises CliError on non-zero exit, unparseable output, or timeout.
    """
    command = [CLI_NAME, *args]
    try:
        result = subprocess.run(
            command,
            input=stdin_text,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
        )
    except subprocess.TimeoutExpired as exc:
        raise CliError("timeout", f"obvious CLI timed out after {timeout}s") from exc
    except FileNotFoundError as exc:
        raise CliError("cli_missing", "obvious CLI not found on PATH") from exc

    if result.returncode != 0:
        detail = _excerpt(result.stderr) or _excerpt(result.stdout)
        raise CliError("cli_failed", detail or f"obvious CLI exited with code {result.returncode}")

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise CliError(
            "invalid_output",
            f"obvious CLI printed non-JSON output: {_excerpt(result.stdout)}",
        ) from exc
