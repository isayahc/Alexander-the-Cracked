"""Tool-level tests against a fake CLI runner: happy paths and typed error paths."""

from __future__ import annotations

import pytest
from fastmcp.exceptions import ToolError

from obvious_mcp_bridge import server
from obvious_mcp_bridge.runner import CliError

from .conftest import FakeCli


class TestListTasks:
    def test_happy_path_no_filter(self, fake_cli: FakeCli) -> None:
        fake_cli._result = {"tasks": [{"id": "todo_1", "title": "ship it"}]}
        result = server.list_tasks()
        assert result == {"tasks": [{"id": "todo_1", "title": "ship it"}]}
        assert fake_cli.last.args == ["tasks", "list"]

    def test_happy_path_with_status(self, fake_cli: FakeCli) -> None:
        server.list_tasks(status="in_progress")
        assert fake_cli.last.args == ["tasks", "list", "--status=in_progress"]

    def test_cli_failure_is_tool_error(self, failing_cli) -> None:
        failing_cli(CliError("cli_failed", "unknown command 'tasks'"))
        with pytest.raises(ToolError, match="cli_failed.*unknown command"):
            server.list_tasks()


class TestCreateTask:
    def test_happy_path_full(self, fake_cli: FakeCli) -> None:
        fake_cli._result = {"id": "todo_new", "title": "Do the thing"}
        result = server.create_task(
            title="Do the thing", description="carefully", assignee="coder"
        )
        assert result == {"id": "todo_new", "title": "Do the thing"}
        assert fake_cli.last.args == [
            "tasks",
            "create",
            "--title=Do the thing",
            "--description=carefully",
            "--assignee=coder",
        ]

    def test_optional_fields_omitted_when_empty(self, fake_cli: FakeCli) -> None:
        server.create_task(title="minimal")
        assert fake_cli.last.args == ["tasks", "create", "--title=minimal"]

    def test_cli_failure_is_tool_error(self, failing_cli) -> None:
        failing_cli(CliError("cli_failed", "title is required"))
        with pytest.raises(ToolError, match="title is required"):
            server.create_task(title="x")


class TestUpdateTask:
    def test_happy_path_status_and_note(self, fake_cli: FakeCli) -> None:
        fake_cli._result = {"id": "todo_1", "status": "completed"}
        result = server.update_task(
            task_id="todo_1", status="completed", completion_note="done"
        )
        assert result == {"id": "todo_1", "status": "completed"}
        assert fake_cli.last.args == [
            "tasks",
            "update",
            "--taskId=todo_1",
            "--status=completed",
            "--completionNote=done",
        ]

    def test_error_when_both_fields_empty(self, fake_cli: FakeCli) -> None:
        with pytest.raises(ToolError, match="requires status and/or completion_note"):
            server.update_task(task_id="todo_1")
        assert not fake_cli.invocations

    def test_cli_failure_is_tool_error(self, failing_cli) -> None:
        failing_cli(CliError("cli_failed", "no task todo_zzz"))
        with pytest.raises(ToolError, match="todo_zzz"):
            server.update_task(task_id="todo_zzz", status="completed")


class TestCreateDocument:
    def test_happy_path_pipes_markdown_via_stdin(self, fake_cli: FakeCli) -> None:
        fake_cli._result = {"id": "art_1", "name": "Notes"}
        result = server.create_document(name="Notes", markdown="# Notes\n\nbody")
        assert result == {"id": "art_1", "name": "Notes"}
        invocation = fake_cli.last
        assert invocation.args == ["artifacts", "create", "--type=document", "--name=Notes"]
        assert invocation.stdin_text == "# Notes\n\nbody"

    def test_description_omitted_when_empty(self, fake_cli: FakeCli) -> None:
        server.create_document(name="N", markdown="body", description="d")
        assert "--description=d" in fake_cli.last.args

    def test_cli_failure_is_tool_error(self, failing_cli) -> None:
        failing_cli(CliError("cli_failed", "name is required"))
        with pytest.raises(ToolError, match="name is required"):
            server.create_document(name="", markdown="x")


class TestRunnerErrorMapping:
    """The runner itself maps every failure mode to a typed CliError (no real CLI)."""

    def test_invalid_output(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import obvious_mcp_bridge.runner as runner

        class FakeCompleted:
            returncode = 0
            stdout = "not json at all"
            stderr = ""

        monkeypatch.setattr("subprocess.run", lambda *a, **k: FakeCompleted())
        with pytest.raises(CliError, match="invalid_output"):
            runner.run_cli(["tasks", "list"])

    def test_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import subprocess

        import obvious_mcp_bridge.runner as runner

        def explode(*a, **k):
            raise subprocess.TimeoutExpired(cmd="obvious", timeout=60)

        monkeypatch.setattr("subprocess.run", explode)
        with pytest.raises(CliError, match="timeout"):
            runner.run_cli(["tasks", "list"])
