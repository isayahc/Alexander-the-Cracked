"""The default backend: dispatch each build to an Obvious coding agent.

Each attempt creates and starts an Obvious task (`obvious tasks create
--assignee=coder --start=true`), polls `obvious tasks get` until the worker
reports a terminal status, then hands the produced directory back to the build
loop for test verification. Credentials are never handled here — the obvious
CLI reads the ambient API_TOKEN from the environment exactly as SDK scripts do.
The command runner is injectable so tests never spawn real tasks.
"""

import asyncio
import json
import re
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

from alexander.builder.agent import (
    AgentAttemptFn,
    AgentBackendError,
    AttemptLoopBuilder,
    AttemptOutcome,
)

_POLL_INTERVAL_S = 5.0
# Terminal statuses observed in `obvious tasks get` output (task.transitions).
_SUCCESS_STATUSES = {"completed"}
_FAILURE_STATUSES = {"failed", "cancelled", "needs_action"}
_IN_PROGRESS_STATUSES = {None, "", "pending", "scheduled", "paused", "blocked", "in_progress"}

type CommandRunner = Callable[[list[str]], str]


class ObviousCliError(RuntimeError):
    """Raised when an obvious CLI invocation exits non-zero."""


def default_command_runner(argv: list[str]) -> str:
    """Run an obvious CLI command and return its stdout."""
    proc = subprocess.run(argv, capture_output=True, text=True, check=False)
    if proc.returncode == 0:
        return proc.stdout
    detail = proc.stderr.strip() or proc.stdout.strip() or f"exit code {proc.returncode}"
    raise ObviousCliError(f"{' '.join(argv[:2])} failed: {detail}")


def title_from_prompt(prompt: str) -> str:
    """Derive a task title from the rendered prompt's Event line, with a fallback."""
    for line in prompt.splitlines():
        if line.startswith("Event: "):
            event = line.removeprefix("Event: ").strip()[:80]
            return f"Build {event} project"
    return "Alexander project build"


def _task_id_from_output(output: str) -> str:
    """Extract the created task id from `tasks create` output (JSON or text)."""
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict):
        nested = payload.get("task")
        candidates = [payload.get("id"), nested.get("id") if isinstance(nested, dict) else None]
        for candidate in candidates:
            if isinstance(candidate, str) and candidate:
                return candidate
    match = re.search(r"todo_[A-Za-z0-9]+", output)
    if match:
        return match.group(0)
    raise ObviousCliError(f"could not find a task id in tasks create output: {output[:200]}")


def _field_from_output(output: str, field: str) -> str | None:
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        return None
    if isinstance(payload, dict):
        value = payload.get(field)
        if isinstance(value, str):
            return value
    return None


def obvious_attempt(
    runner: CommandRunner | None = None,
    poll_interval_s: float = _POLL_INTERVAL_S,
    clock: Callable[[], float] = time.monotonic,
) -> AgentAttemptFn:
    """Build an AgentAttemptFn that dispatches the build to an Obvious coding agent."""
    run = runner if runner is not None else default_command_runner

    async def attempt(prompt: str, cwd: Path, timeout_s: float) -> AttemptOutcome:
        out_dir = Path(cwd).absolute()
        description = (
            f"{prompt}\n\n"
            f"Write the finished project into this exact directory: {out_dir}\n"
            "(create it if needed). The project must include SPEC.md, a runnable\n"
            "implementation, a test suite, and a README.md pitch."
        )
        try:
            create_out = await asyncio.to_thread(
                run,
                [
                    "obvious",
                    "tasks",
                    "create",
                    f"--title={title_from_prompt(prompt)}",
                    "--assignee=coder",
                    f"--description={description}",
                    "--start=true",
                ],
            )
            task_id = _task_id_from_output(create_out)
        except FileNotFoundError as exc:
            raise AgentBackendError(
                "the obvious CLI was not found on PATH — install it and try again, "
                "or point ALEXANDER_BUILD_BACKEND at another backend"
            ) from exc
        except ObviousCliError as exc:
            raise AgentBackendError(f"obvious CLI task creation failed: {exc}") from exc

        deadline = clock() + timeout_s
        while True:
            get_argv = ["obvious", "tasks", "get", f"--taskId={task_id}"]
            get_out = await asyncio.to_thread(run, get_argv)
            status = _field_from_output(get_out, "status")
            if status in _SUCCESS_STATUSES:
                note = _field_from_output(get_out, "completionNote") or ""
                return AttemptOutcome(text=note or f"worker task {task_id} completed")
            if status in _FAILURE_STATUSES:
                note = _field_from_output(get_out, "completionNote") or ""
                return AttemptOutcome(
                    is_error=True,
                    error=(
                        f"Obvious coding agent reported status {status!r} "
                        f"for task {task_id}: {note}"
                    ),
                )
            if status not in _IN_PROGRESS_STATUSES:
                return AttemptOutcome(
                    is_error=True,
                    error=f"Obvious task {task_id} reported unrecognized status {status!r}",
                )
            if clock() >= deadline:
                return AttemptOutcome(
                    is_error=True,
                    error=(
                        f"Obvious coding agent for task {task_id} did not finish within "
                        f"the build budget (status: {status or 'unknown'})"
                    ),
                )
            await asyncio.sleep(poll_interval_s)

    return attempt


class ObviousBackend(AttemptLoopBuilder):
    """Default ProjectBuilder: dispatches builds to Obvious coding agents.

    Each attempt dispatches one Obvious task (created with --start=true) and
    waits for its terminal status; the build loop then verifies the produced
    directory's tests. A failing worker consumes another attempt, dispatching
    a fresh task with the failure feedback appended.
    """

    def __init__(
        self,
        runner: CommandRunner | None = None,
        poll_interval_s: float = _POLL_INTERVAL_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(obvious_attempt(runner, poll_interval_s, clock), clock)
