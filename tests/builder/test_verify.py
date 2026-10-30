"""Test-suite detection and execution for generated projects."""

import json

from alexander.builder.verify import detect_test_command, run_tests


def test_detects_pytest_project(tmp_path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    command = detect_test_command(tmp_path)
    assert command is not None
    assert command[-2:] == ["pytest", "-q"]


def test_detects_top_level_test_files(tmp_path) -> None:
    (tmp_path / "test_thing.py").write_text("def test_x(): pass\n", encoding="utf-8")
    assert detect_test_command(tmp_path) is not None


def test_detects_npm_test_script(tmp_path) -> None:
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"test": "vitest"}}), encoding="utf-8"
    )
    assert detect_test_command(tmp_path) == ["npm", "test", "--silent"]


def test_ignores_npm_without_test_script(tmp_path) -> None:
    manifest = json.dumps({"scripts": {"lint": "eslint"}})
    (tmp_path / "package.json").write_text(manifest, encoding="utf-8")
    assert detect_test_command(tmp_path) is None


def test_no_suite_detected(tmp_path) -> None:
    assert detect_test_command(tmp_path) is None


def test_run_tests_passes(tmp_path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    (tmp_path / "test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    run = run_tests(tmp_path, timeout_s=60)
    assert run.passed
    assert "passed" in run.summary


def test_run_tests_fails(tmp_path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    (tmp_path / "test_bad.py").write_text("def test_bad():\n    assert 1 == 2\n", encoding="utf-8")
    run = run_tests(tmp_path, timeout_s=60)
    assert not run.passed
    assert "failed" in run.summary


def test_run_tests_without_suite(tmp_path) -> None:
    run = run_tests(tmp_path, timeout_s=60)
    assert not run.passed
    assert "no test suite detected" in run.summary
