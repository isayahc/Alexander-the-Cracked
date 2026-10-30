"""Repository-creation backends: the ``gh`` CLI and an offline fixture.

Both backends honor one contract: ``create`` never raises for "the remote
already has this name" — it returns ``EXISTS`` with the identity it found.
That turns the crash window between remote creation and manifest write into
a self-healing no-op instead of a duplicate.

``seed`` is the corruption guard for content: it pushes an initial commit
from a build directory only when the remote has zero commits, and refuses
outright otherwise. A push may happen once or not at all — never twice,
never over existing history.
"""

import json
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from alexander.repos.models import CreateOutcome, RemoteIdentity, RepoSpec

# Copy-out ignore set for seeding: local VCS and interpreter noise never
# belongs in a fresh repository.
_SEED_IGNORE = shutil.ignore_patterns(".git", "__pycache__", "*.pyc")


class CreatorError(RuntimeError):
    """A backend operation failed and the remote is in an unknown-or-unchanged state."""


class SeedRefusedError(RuntimeError):
    """Seeding was refused: the remote is not empty, so nothing was touched."""


@dataclass(frozen=True)
class CreateReply:
    """What a backend's ``create`` reports."""

    outcome: CreateOutcome
    identity: RemoteIdentity


class RepoCreator(Protocol):
    """The backend contract: idempotent creation, guarded seeding."""

    name: str

    def create(self, spec: RepoSpec) -> CreateReply: ...

    def seed(self, spec: RepoSpec, identity: RemoteIdentity) -> str: ...


class FixtureRepoCreator:
    """In-memory backend: no network, deterministic, inspectable.

    Doubles as the offline ``fixture`` CLI backend for demo runs and the
    test double for the idempotency suite.
    """

    name = "fixture"

    def __init__(self, owner: str = "fixture-owner") -> None:
        self.owner = owner
        self.repos: dict[str, RemoteIdentity] = {}
        self.create_calls: list[str] = []
        self.seed_calls: list[str] = []
        self.seeded: set[str] = set()
        self.non_empty: set[str] = set()  # names where seed() must refuse

    def create(self, spec: RepoSpec) -> CreateReply:
        self.create_calls.append(spec.name)
        identity = self.repos.get(spec.name)
        if identity is None:
            url = f"https://example.com/{self.owner}/{spec.name}"
            identity = RemoteIdentity(owner=self.owner, url=url)
            self.repos[spec.name] = identity
            return CreateReply(outcome=CreateOutcome.CREATED, identity=identity)
        return CreateReply(outcome=CreateOutcome.EXISTS, identity=identity)

    def seed(self, spec: RepoSpec, identity: RemoteIdentity) -> str:
        """Mark seeded; refuse when told to simulate a non-empty remote."""
        self.seed_calls.append(spec.name)
        if spec.name in self.non_empty:
            raise SeedRefusedError(f"fixture remote {spec.name!r} is not empty")
        self.seeded.add(spec.name)
        return f"seeded {identity.url} from {spec.source_dir}"


class GhRepoCreator:
    """Backend over the ``gh`` CLI, using the caller's GitHub authentication."""

    name = "gh"

    def __init__(
        self,
        runner: Callable[[list[str]], subprocess.CompletedProcess[str]] | None = None,
    ) -> None:
        self._run = runner if runner is not None else self._subprocess_run

    @staticmethod
    def _subprocess_run(argv: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(argv, capture_output=True, text=True, check=False)

    def create(self, spec: RepoSpec) -> CreateReply:
        visibility = "--private" if spec.private else "--public"
        result = self._run(
            ["gh", "repo", "create", spec.name, visibility,
             "--description", spec.description or "Alexander build"]
        )
        if result.returncode == 0:
            return CreateReply(outcome=CreateOutcome.CREATED, identity=self._identity(spec.name))
        combined = f"{result.stdout}{result.stderr}"
        if "already exists" in combined.lower():
            return CreateReply(outcome=CreateOutcome.EXISTS, identity=self._identity(spec.name))
        raise CreatorError(f"gh repo create failed: {combined.strip()}")

    def seed(self, spec: RepoSpec, identity: RemoteIdentity) -> str:
        """Initial push from ``spec.source_dir``; refuse unless the remote is empty."""
        if spec.source_dir is None:
            raise CreatorError("cannot seed without a source directory")
        if not spec.source_dir.is_dir():
            raise CreatorError(f"source directory not found: {spec.source_dir}")
        if self._remote_has_commits(identity.url):
            raise SeedRefusedError(
                f"remote for {spec.name!r} already has commits; refusing to touch it"
            )
        with tempfile.TemporaryDirectory(prefix="alexander-seed-") as work:
            worktree = Path(work) / "seed"
            worktree.mkdir()
            shutil.copytree(spec.source_dir, worktree, dirs_exist_ok=True, ignore=_SEED_IGNORE)
            git = [
                "git", "-C", str(worktree),
                "-c", "user.name=Alexander",
                "-c", "user.email=alexander@localhost",
            ]
            for argv in (
                ["git", "init", "-b", "main", str(worktree)],
                [*git, "add", "-A"],
                [*git, "commit", "-m", f"Initial commit: {spec.slug} build"],
                [*git, "remote", "add", "origin", identity.url],
            ):
                result = self._run(argv)
                if result.returncode != 0:
                    raise CreatorError(f"{' '.join(argv[:2])} failed: {result.stderr.strip()}")
            push = self._run([*git, "push", "origin", "main"])
            if push.returncode != 0:
                raise CreatorError(f"git push failed: {push.stderr.strip()}")
        return f"pushed {spec.source_dir} to {identity.url}"

    def _identity(self, name: str) -> RemoteIdentity:
        result = self._run(["gh", "repo", "view", name, "--json", "url", "owner"])
        if result.returncode != 0:
            raise CreatorError(f"gh repo view {name} failed: {result.stderr.strip()}")
        payload = json.loads(result.stdout)
        return RemoteIdentity(owner=payload["owner"]["login"], url=payload["url"])

    def _remote_has_commits(self, url: str) -> bool:
        result = self._run(["git", "ls-remote", url, "HEAD"])
        if result.returncode != 0:
            raise CreatorError(f"git ls-remote failed: {result.stderr.strip()}")
        return bool(result.stdout.strip())
