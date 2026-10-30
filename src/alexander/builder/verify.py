"""Detect and run a generated project's test suite (subprocess edge, bounded)."""

import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

_SUMMARY_CHARS = 600


@dataclass(frozen=True)
class TestRun:
    """Result of running a generated project's tests once."""

    passed: bool
    summary: str


def detect_test_command(out_dir: Path) -> list[str] | None:
    """Pick a test command for the project layout, or None if no suite is detected."""
    if _has_pytest(out_dir):
        return [sys.executable, "-m", "pytest", "-q"]
    npm_command = _npm_test_command(out_dir)
    if npm_command is not None:
        return npm_command
    return None


def run_tests(out_dir: Path, timeout_s: float) -> TestRun:
    """Run the detected test suite once, bounded by timeout_s."""
    command = detect_test_command(out_dir)
    if command is None:
        return TestRun(False, "no test suite detected; add tests (e.g. pytest)")
    # Generated projects get rewritten between attempts, often within the same
    # second and at identical file size — the (mtime-second, size) pyc key can
    # then serve stale bytecode. Verify against a fresh bytecode cache each run.
    with tempfile.TemporaryDirectory(prefix="alexander-pyc-") as pycache_prefix:
        env = {**os.environ, "PYTHONPYCACHEPREFIX": pycache_prefix}
        try:
            proc = subprocess.run(
                command,
                cwd=out_dir,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                check=False,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return TestRun(False, f"tests timed out after {timeout_s:.0f}s")
        except OSError as exc:
            return TestRun(False, f"could not run tests: {exc}")
    return TestRun(proc.returncode == 0, _summarize(proc))


def _has_pytest(out_dir: Path) -> bool:
    markers = ("pytest.ini", "pyproject.toml", "setup.cfg")
    if any((out_dir / marker).exists() for marker in markers):
        return True
    if (out_dir / "tests").is_dir():
        return True
    return bool(list(out_dir.glob("test_*.py")) or list(out_dir.glob("*_test.py")))


def _npm_test_command(out_dir: Path) -> list[str] | None:
    manifest = out_dir / "package.json"
    if not manifest.exists():
        return None
    try:
        package = json.loads(manifest.read_text(encoding="utf-8"))
        scripts = package.get("scripts", {})
    except (json.JSONDecodeError, AttributeError):
        return None
    if isinstance(scripts, dict) and "test" in scripts:
        return ["npm", "test", "--silent"]
    return None


_PASS_SUMMARY_RE = re.compile(r"\b\d+ passed\b")


def _pass_evidence(output: str) -> str:
    # A passing run's last line can be plugin noise (e.g. a deprecation
    # warning); anchor on pytest's own "N passed" summary instead.
    for line in reversed(output.splitlines()):
        if _PASS_SUMMARY_RE.search(line):
            return line.strip()
    last_line = output.rsplit("\n", 1)[-1] if output else ""
    return last_line


def _summarize(proc: subprocess.CompletedProcess[str]) -> str:
    output = "\n".join(filter(None, [proc.stdout.strip(), proc.stderr.strip()]))
    if proc.returncode == 0:
        summary = _pass_evidence(output)
        return f"tests passed: {summary}" if summary else "tests passed"
    prefix = "..." if len(output) > _SUMMARY_CHARS else ""
    return f"tests failed:\n{prefix}{output[-_SUMMARY_CHARS:]}"
