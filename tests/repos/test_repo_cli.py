"""CLI: `alexander repo create` end-to-end against the offline fixture backend."""

import json

from click.testing import CliRunner

from alexander.cli import cli


def run_create(manifest_path, source=None, slug="demo-event", extra=None):
    args = [
        "repo", "create", "--slug", slug, "--backend", "fixture",
        "--manifest", str(manifest_path),
    ]
    if source is not None:
        args += ["--from", str(source)]
    if extra:
        args += extra
    return CliRunner().invoke(cli, args)


def test_first_run_creates_and_second_is_a_noop(tmp_path):
    manifest = tmp_path / "manifest.json"

    first = run_create(manifest)
    assert first.exit_code == 0, first.output
    assert "created https://example.com/fixture-owner/demo-event" in first.output

    second = run_create(manifest)
    assert second.exit_code == 0, second.output
    assert "already on record, nothing done" in second.output

    payload = json.loads(manifest.read_text())
    assert list(payload["repos"]) == ["demo-event"]


def test_run_with_source_seeds_once(tmp_path):
    manifest = tmp_path / "manifest.json"
    build = tmp_path / "builds" / "demo-event"
    build.mkdir(parents=True)
    (build / "README.md").write_text("a built project")

    first = run_create(manifest, source=build)
    assert first.exit_code == 0, first.output
    assert "seeded" in first.output

    second = run_create(manifest, source=build)
    assert second.exit_code == 0, second.output
    assert "seeded" not in second.output  # re-run never re-seeds


def test_invalid_repo_name_is_a_usage_error(tmp_path):
    result = run_create(tmp_path / "manifest.json", extra=["--name", ".bad-name"])
    assert result.exit_code != 0
    assert "must not start with" in result.output


def test_no_source_dir_means_no_seeding_message(tmp_path):
    result = run_create(tmp_path / "manifest.json")
    assert result.exit_code == 0
    assert "seeded" not in result.output
