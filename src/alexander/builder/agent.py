"""The build loop: bounded agent attempts that produce a tested project directory.

The loop (`run_build_loop`) is backend-agnostic: it drives an injected
`AgentAttemptFn` under attempt and wall-clock budgets, verifies the produced
project's tests, and guarantees a README/pitch. Backends plug in as attempt
functions — the Claude Agent SDK adapter lives here, the Obvious CLI adapter
in `obvious.py` — so either can be swapped without touching the loop.
"""

import asyncio
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKError, ResultMessage, query

from alexander.builder.models import BuildBudgets, BuildResult, BuildStatus, HackathonBrief
from alexander.builder.prompts import render_attempt_prompt, render_fallback_readme
from alexander.builder.verify import TestRun, run_tests

_ALLOWED_TOOLS = ["Read", "Write", "Edit", "Bash", "Glob", "Grep"]


class MissingApiKeyError(RuntimeError):
    """Raised when ANTHROPIC_API_KEY is unset but the Claude Agent SDK needs it."""


class AgentBackendError(RuntimeError):
    """Raised when an agent backend itself fails (environment problem, not retried)."""


def ensure_api_key() -> str:
    """Return the configured Anthropic API key, or raise a friendly setup error."""
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        raise MissingApiKeyError(
            "ANTHROPIC_API_KEY is not set, so the Claude backend cannot run its coding "
            "agent. Get a key at https://console.anthropic.com/settings/keys, then export "
            "it (export ANTHROPIC_API_KEY=sk-ant-...) or put it in .env (see .env.example) "
            "and try again — or use the default 'obvious' backend (ALEXANDER_BUILD_BACKEND)."
        )
    return key


@dataclass(frozen=True)
class AttemptOutcome:
    """What one agent attempt returned, flattened out of backend message types."""

    text: str | None = None
    is_error: bool = False
    num_turns: int = 0
    duration_ms: int | None = None
    error: str | None = None


type AgentAttemptFn = Callable[[str, Path, float], Awaitable[AttemptOutcome]]


class ProjectBuilder(Protocol):
    """The builder seam: implement this to swap the agent backend."""

    async def build(
        self, brief: HackathonBrief, out_dir: Path, budgets: BuildBudgets
    ) -> BuildResult: ...


async def claude_attempt(prompt: str, cwd: Path, timeout_s: float) -> AttemptOutcome:
    """Run one Claude Agent SDK attempt inside cwd, bounded by timeout_s."""
    options = ClaudeAgentOptions(
        cwd=str(cwd),
        allowed_tools=list(_ALLOWED_TOOLS),
        permission_mode="bypassPermissions",
        env={"ANTHROPIC_API_KEY": ensure_api_key()},
    )
    result: ResultMessage | None = None
    try:
        async with asyncio.timeout(timeout_s):
            async for message in query(prompt=prompt, options=options):
                if isinstance(message, ResultMessage):
                    result = message
    except TimeoutError:
        return AttemptOutcome(error=f"attempt timed out after {timeout_s:.0f}s", is_error=True)
    except ClaudeSDKError as exc:
        raise AgentBackendError(f"Claude Agent SDK failed: {exc}") from exc
    if result is None:
        return AttemptOutcome(error="agent ended without a result message", is_error=True)
    return AttemptOutcome(
        text=result.result,
        is_error=result.is_error,
        num_turns=result.num_turns,
        duration_ms=result.duration_ms,
    )


async def run_build_loop(
    attempt_fn: AgentAttemptFn,
    brief: HackathonBrief,
    out_dir: Path,
    budgets: BuildBudgets,
    clock: Callable[[], float] = time.monotonic,
) -> BuildResult:
    """Run bounded agent attempts until the generated project's tests pass.

    Returns SUCCESS once the generated tests pass; ERROR when the agent backend
    itself fails (an environment problem, not retried); BUDGET_EXHAUSTED when
    the attempt or wall-clock budget runs out first. MissingApiKeyError and
    other setup errors propagate to the caller.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    deadline = clock() + budgets.wall_clock.total_seconds()
    failure_notes = ""
    last_test: TestRun | None = None
    attempts_used = 0
    error: str | None = None

    for attempt_no in range(1, budgets.max_attempts + 1):
        remaining = deadline - clock()
        if remaining <= 0:
            break
        prompt = render_attempt_prompt(brief, attempt_no, budgets.max_attempts, failure_notes)
        try:
            outcome = await attempt_fn(prompt, out_dir, remaining)
        except AgentBackendError as exc:
            error = f"agent backend failed on attempt {attempt_no}: {exc}"
            attempts_used = attempt_no
            break
        attempts_used = attempt_no
        if outcome.is_error:
            reason = outcome.error or outcome.text or "unknown reason"
            failure_notes = f"the agent run itself failed: {reason}"
            continue
        remaining = deadline - clock()
        if remaining <= 0:
            break
        test = run_tests(out_dir, timeout_s=remaining)
        last_test = test
        if test.passed:
            _ensure_readme(out_dir, brief, test.summary)
            return BuildResult(
                status=BuildStatus.SUCCESS,
                artifact_path=out_dir,
                test_summary=test.summary,
                attempts_used=attempts_used,
            )
        failure_notes = f"tests failed on attempt {attempt_no}: {test.summary}"

    status = BuildStatus.ERROR if error is not None else BuildStatus.BUDGET_EXHAUSTED
    return BuildResult(
        status=status,
        artifact_path=out_dir,
        test_summary=last_test.summary if last_test else None,
        attempts_used=attempts_used,
        error=error or (failure_notes or None),
    )


class AttemptLoopBuilder:
    """Shared engine: drives one injected AgentAttemptFn through the budgeted loop."""

    def __init__(
        self,
        attempt_fn: AgentAttemptFn,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._attempt = attempt_fn
        self._clock = clock

    async def build(
        self, brief: HackathonBrief, out_dir: Path, budgets: BuildBudgets
    ) -> BuildResult:
        return await run_build_loop(self._attempt, brief, out_dir, budgets, self._clock)


class ClaudeAgentBuilder(AttemptLoopBuilder):
    """ProjectBuilder backed by the Claude Agent SDK (the optional backend).

    The SDK lives only inside the attempt function; inject a different
    `attempt_fn` (a scripted fake in tests, or another backend later) and
    everything else — budgets, verification, README fallback — is reused
    unchanged.
    """

    def __init__(
        self,
        attempt_fn: AgentAttemptFn | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(attempt_fn if attempt_fn is not None else claude_attempt, clock)


def _ensure_readme(out_dir: Path, brief: HackathonBrief, test_summary: str) -> None:
    """Write a minimal README/pitch when the agent finished without one."""
    readme = out_dir / "README.md"
    if not readme.exists():
        readme.write_text(render_fallback_readme(brief, test_summary), encoding="utf-8")
