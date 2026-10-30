"""CLI `alexander iterate` behaviour with a scripted builder (no backend, no network)."""

import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from conftest import ScriptedBuilder, write_failing_project, write_passing_project

from alexander.cli import cli
from alexander.iteration import IterationManifest, manifest_path_for


@pytest.fixture
def brief_file(tmp_path: Path, brief) -> Path:
    path = tmp_path / "brief.json"
    path.write_text(brief.model_dump_json(), encoding="utf-8")
    return path


def run_iterate(brief_file: Path, out_dir: Path, max_iterations: int = 2):
    runner = CliRunner()
    return runner.invoke(
        cli,
        [
            "iterate",
            "--brief",
            str(brief_file),
            "--out",
            str(out_dir),
            "--max-iterations",
            str(max_iterations),
        ],
        catch_exceptions=False,
    )


def test_iterate_reports_a_full_loop_and_exits_zero(tmp_path, brief_file, monkeypatch) -> None:
    out_dir = tmp_path / "build"
    monkeypatch.setattr(
        "alexander.cli.create_builder",
        lambda backend=None: ScriptedBuilder([write_failing_project, write_passing_project]),
    )

    result = run_iterate(brief_file, out_dir, max_iterations=3)

    assert result.exit_code == 0
    assert "iteration 1: failed" in result.output
    assert "iteration 2: passed" in result.output
    assert "stopped: pass_condition" in result.output
    assert "best-known result:" in result.output
    assert "total cost: 2 attempts" in result.output
    assert "manifest:" in result.output


def test_iterate_exits_nonzero_when_budget_exhausts_without_a_pass(
    tmp_path, brief_file, monkeypatch
) -> None:
    out_dir = tmp_path / "build"
    monkeypatch.setattr(
        "alexander.cli.create_builder",
        lambda backend=None: ScriptedBuilder([write_failing_project]),
    )

    result = run_iterate(brief_file, out_dir, max_iterations=2)

    assert result.exit_code == 1
    assert "stopped: budget_iterations" in result.output


def test_iterate_writes_a_reloadable_manifest(tmp_path, brief_file, monkeypatch) -> None:
    out_dir = tmp_path / "build"
    monkeypatch.setattr(
        "alexander.cli.create_builder",
        lambda backend=None: ScriptedBuilder([write_passing_project]),
    )

    result = run_iterate(brief_file, out_dir, max_iterations=1)

    assert result.exit_code == 0
    path = manifest_path_for(out_dir)
    manifest = IterationManifest.model_validate_json(path.read_text(encoding="utf-8"))
    assert manifest.stop_reason.value == "pass_condition"
    assert json.loads(path.read_text())["iterations"][0]["passed"] is True


def test_iterate_rejects_an_invalid_brief(tmp_path) -> None:
    bad = tmp_path / "brief.json"
    bad.write_text("not json at all", encoding="utf-8")
    runner = CliRunner()

    result = runner.invoke(
        cli, ["iterate", "--brief", str(bad), "--out", str(tmp_path / "b")], catch_exceptions=False
    )

    assert result.exit_code == 1
    assert "not a valid brief" in result.output
