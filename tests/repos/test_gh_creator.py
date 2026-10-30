"""GhRepoCreator against a scripted ``gh``/``git`` runner: parsing and guards."""

import subprocess
from pathlib import Path

import pytest

from alexander.repos.creator import CreatorError, GhRepoCreator, SeedRefusedError
from alexander.repos.models import CreateOutcome, RemoteIdentity, RepoSpec


class FakeRunner:
    """Scripted runner: maps a matcher to (returncode, stdout, stderr)."""

    def __init__(self, responses):
        self.responses = responses  # list of (predicate, response)
        self.calls: list[list[str]] = []

    def __call__(self, argv):
        self.calls.append(argv)
        for predicate, response in self.responses:
            if predicate(argv):
                return subprocess.CompletedProcess(argv, *response)
        raise AssertionError(f"unexpected command: {argv}")


def gh_view(name="https://github.com/octocat/demo-event"):
    return (
        0,
        f'{{"url": "{name}", "owner": {{"login": "octocat"}}}}',
        "",
    )


class SnapshotRunner(FakeRunner):
    """FakeRunner that records the worktree listing at each ``git add -A``."""

    def __init__(self, responses):
        super().__init__(responses)
        self.snapshot: set[Path] = set()

    def __call__(self, argv):
        result = super().__call__(argv)
        if argv[-1] == "-A":
            worktree = Path(argv[2])
            self.snapshot = {p.relative_to(worktree) for p in worktree.rglob("*")}
        return result


def test_create_success_parses_identity():
    runner = FakeRunner([
        (lambda a: a[:3] == ["gh", "repo", "create"], (0, "", "")),
        (lambda a: a[:3] == ["gh", "repo", "view"], gh_view()),
    ])
    creator = GhRepoCreator(runner=runner)
    reply = creator.create(RepoSpec(slug="demo-event", name="demo-event"))
    assert reply.outcome is CreateOutcome.CREATED
    assert reply.identity.url == "https://github.com/octocat/demo-event"
    assert reply.identity.owner == "octocat"


def test_create_already_exists_adopts_the_repo():
    runner = FakeRunner([
        (lambda a: a[:3] == ["gh", "repo", "create"],
         (1, "", "repository with the name demo-event already exists")),
        (lambda a: a[:3] == ["gh", "repo", "view"], gh_view()),
    ])
    creator = GhRepoCreator(runner=runner)
    reply = creator.create(RepoSpec(slug="demo-event", name="demo-event"))
    assert reply.outcome is CreateOutcome.EXISTS  # the heal path, not an error


def test_create_other_failure_is_loud():
    runner = FakeRunner([
        (lambda a: a[:3] == ["gh", "repo", "create"], (1, "", "auth failure")),
    ])
    creator = GhRepoCreator(runner=runner)
    with pytest.raises(CreatorError, match="auth failure"):
        creator.create(RepoSpec(slug="demo-event", name="demo-event"))


def gh_identity() -> RemoteIdentity:
    return RemoteIdentity(owner="octocat", url="https://github.com/octocat/demo")


def test_seed_refuses_when_remote_has_commits(tmp_path):
    source = tmp_path / "build"
    source.mkdir()
    runner = FakeRunner([
        (lambda a: a[:2] == ["git", "ls-remote"], (0, "abc123\trefs/heads/main\n", "")),
    ])
    creator = GhRepoCreator(runner=runner)
    spec = RepoSpec(slug="s", name="s", source_dir=source)
    with pytest.raises(SeedRefusedError, match="refusing to touch"):
        creator.seed(spec, gh_identity())


def test_seed_pushes_initial_commit_from_source(tmp_path):
    source = tmp_path / "build"
    source.mkdir()
    (source / "app.py").write_text("print('hi')")
    (source / ".git").mkdir()  # must be excluded from the copy
    (source / ".git" / "HEAD").write_text("ref: refs/heads/main")
    (source / "__pycache__").mkdir()
    (source / "__pycache__" / "app.cpython-312.pyc").write_text("junk")

    # Empty remote (ls-remote returns nothing), every git step succeeds.
    runner = SnapshotRunner([
        (lambda a: a[:2] == ["git", "ls-remote"], (0, "", "")),
        (lambda a: a[:2] in (["git", "-C"], ["git", "init"]), (0, "", "")),
    ])
    creator = GhRepoCreator(runner=runner)
    detail = creator.seed(
        RepoSpec(slug="demo-event", name="demo-event", source_dir=source), gh_identity()
    )
    assert "pushed" in detail
    pushes = [a for a in runner.calls if a[-3:] == ["push", "origin", "main"]]
    assert len(pushes) == 1
    # The commit message names the slug; git identity is explicit, not ambient.
    commit_cmd = next(a for a in runner.calls if "commit" in a)
    assert "Initial commit: demo-event build" in commit_cmd
    assert any("user.name=Alexander" in a for a in commit_cmd)
    # VCS/interpreter noise never leaves the build directory: check what the
    # worktree contained when `git add -A` ran (the temp dir is gone after).
    assert Path("app.py") in runner.snapshot
    assert not any(str(p).startswith(".git") for p in runner.snapshot)
    assert not any(str(p).startswith("__pycache__") for p in runner.snapshot)


def test_seed_missing_source_is_loud(tmp_path):
    creator = GhRepoCreator()
    spec = RepoSpec(slug="s", name="s", source_dir=tmp_path / "missing")
    with pytest.raises(CreatorError, match="not found"):
        creator.seed(spec, gh_identity())
