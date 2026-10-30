"""CLI build command: friendly failures without the key, no tracebacks."""

import json

from click.testing import CliRunner

from alexander.cli import cli


def _write_brief(path) -> None:
    path.write_text(
        json.dumps(
            {
                "event_name": "Testathon",
                "description": "A tiny CLI toy",
                "themes": ["fun"],
                "deadline": "2026-12-31",
                "prize": "bragging rights",
            }
        ),
        encoding="utf-8",
    )


def _output_with_stderr(result) -> str:
    # click changed stderr capture across 8.x; combine whatever is available.
    try:
        return result.output + (result.stderr or "")
    except Exception:
        return result.output


def test_build_without_key_prints_friendly_error(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ALEXANDER_BUILD_BACKEND", "claude")
    brief_file = tmp_path / "brief.json"
    _write_brief(brief_file)

    result = CliRunner().invoke(
        cli, ["build", "--brief", str(brief_file), "--out", str(tmp_path / "out")]
    )

    assert result.exit_code == 1
    combined = _output_with_stderr(result)
    assert "ANTHROPIC_API_KEY" in combined
    assert "Traceback" not in combined


def test_build_rejects_invalid_brief(tmp_path) -> None:
    brief_file = tmp_path / "brief.json"
    brief_file.write_text("not json", encoding="utf-8")

    result = CliRunner().invoke(
        cli, ["build", "--brief", str(brief_file), "--out", str(tmp_path / "out")]
    )

    assert result.exit_code == 1
    combined = _output_with_stderr(result)
    assert "not a valid brief" in combined
    assert "Traceback" not in combined


def test_build_rejects_missing_brief_file(tmp_path) -> None:
    result = CliRunner().invoke(
        cli, ["build", "--brief", str(tmp_path / "absent.json"), "--out", str(tmp_path / "out")]
    )

    assert result.exit_code != 0
