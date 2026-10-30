"""Smoke tests: the package imports and the CLI help works offline."""

from click.testing import CliRunner

from alexander import __version__
from alexander.cli import cli


def test_package_imports() -> None:
    assert isinstance(__version__, str)


def test_cli_help() -> None:
    result = CliRunner().invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "discover" in result.output
