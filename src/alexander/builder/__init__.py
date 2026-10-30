"""builder subpackage: turns a HackathonBrief into a tested project directory.

Backend selection (`create_builder`): ALEXANDER_BUILD_BACKEND, default
"obvious" (dispatch to an Obvious coding agent via the obvious CLI);
"claude" activates the Claude Agent SDK backend and requires ANTHROPIC_API_KEY.
"""

import os

from alexander.builder.agent import (
    AgentAttemptFn,
    AgentBackendError,
    AttemptLoopBuilder,
    AttemptOutcome,
    ClaudeAgentBuilder,
    MissingApiKeyError,
    ProjectBuilder,
    claude_attempt,
    ensure_api_key,
    run_build_loop,
)
from alexander.builder.models import (
    BuildBudgets,
    BuildResult,
    BuildStatus,
    HackathonBrief,
)
from alexander.builder.obvious import (
    CommandRunner,
    ObviousBackend,
    ObviousCliError,
)


def create_builder(backend: str | None = None) -> ProjectBuilder:
    """Return the configured ProjectBuilder.

    Reads ALEXANDER_BUILD_BACKEND (default "obvious"); pass `backend` to
    override. The "claude" backend only activates when ANTHROPIC_API_KEY is
    set — otherwise this raises the friendly MissingApiKeyError.
    """
    selected = (backend or os.environ.get("ALEXANDER_BUILD_BACKEND") or "obvious").strip().lower()
    if selected == "obvious":
        return ObviousBackend()
    if selected == "claude":
        ensure_api_key()
        return ClaudeAgentBuilder()
    raise ValueError(f"unknown build backend {selected!r}; expected 'obvious' or 'claude'")


__all__ = [
    "AgentAttemptFn",
    "AgentBackendError",
    "AttemptLoopBuilder",
    "AttemptOutcome",
    "BuildBudgets",
    "BuildResult",
    "BuildStatus",
    "ClaudeAgentBuilder",
    "CommandRunner",
    "HackathonBrief",
    "MissingApiKeyError",
    "ObviousBackend",
    "ObviousCliError",
    "ProjectBuilder",
    "claude_attempt",
    "create_builder",
    "ensure_api_key",
    "run_build_loop",
]
