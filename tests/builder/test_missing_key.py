"""The missing-key path: friendly error, no SDK import-time or traceback garbage."""

import pytest

from alexander.builder import MissingApiKeyError
from alexander.builder.agent import claude_attempt, ensure_api_key


def test_ensure_api_key_raises_friendly_error(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(MissingApiKeyError, match="ANTHROPIC_API_KEY"):
        ensure_api_key()


def test_ensure_api_key_returns_stripped_key(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "  sk-ant-test  ")
    assert ensure_api_key() == "sk-ant-test"


async def test_claude_attempt_requires_key(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(MissingApiKeyError, match="ANTHROPIC_API_KEY"):
        await claude_attempt("build it", tmp_path, timeout_s=10)
