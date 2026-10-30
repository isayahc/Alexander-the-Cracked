"""Backend selection: ALEXANDER_BUILD_BACKEND, default 'obvious'."""

import pytest

from alexander.builder import (
    ClaudeAgentBuilder,
    MissingApiKeyError,
    ObviousBackend,
    create_builder,
)


def test_defaults_to_obvious_backend(monkeypatch) -> None:
    monkeypatch.delenv("ALEXANDER_BUILD_BACKEND", raising=False)
    assert isinstance(create_builder(), ObviousBackend)


def test_env_selects_claude_backend(monkeypatch) -> None:
    monkeypatch.setenv("ALEXANDER_BUILD_BACKEND", "claude")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    assert isinstance(create_builder(), ClaudeAgentBuilder)


def test_claude_backend_requires_api_key(monkeypatch) -> None:
    monkeypatch.setenv("ALEXANDER_BUILD_BACKEND", "claude")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(MissingApiKeyError, match="ANTHROPIC_API_KEY"):
        create_builder()


def test_explicit_backend_overrides_env(monkeypatch) -> None:
    monkeypatch.setenv("ALEXANDER_BUILD_BACKEND", "claude")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    assert isinstance(create_builder("obvious"), ObviousBackend)


def test_unknown_backend_is_rejected(monkeypatch) -> None:
    monkeypatch.delenv("ALEXANDER_BUILD_BACKEND", raising=False)
    with pytest.raises(ValueError, match="unknown build backend"):
        create_builder("magic")
