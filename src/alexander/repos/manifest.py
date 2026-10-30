"""Durable record of repositories Alexander created, keyed by event slug.

This manifest is layer one of the idempotency guarantee: an entry means the
repository is already taken care of, so a re-run never calls the remote at
all. Writes are atomic (tempfile + ``os.replace``) so a crash mid-write can
never leave a half-recorded entry, the same pattern as the discovery cache.

A corrupt manifest is a loud error, not a silent reset: silently starting
from empty would invite duplicate creation. Deleting the file is always a
safe repair — the backend's ``EXISTS`` backstop (layer two) still prevents
duplicates after that.
"""

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from alexander.repos.models import SeedOutcome

MANIFEST_VERSION = 1


def default_manifest_path() -> Path:
    """XDG-sourced default location for the manifest."""
    state_home = os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local" / "state"))
    return Path(state_home) / "alexander" / "repo-manifest.json"


class ManifestCorruptError(ValueError):
    """The manifest file exists but cannot be parsed. Repair or delete it."""


class RepoRecord(BaseModel):
    """One manifest entry: a repository that is already taken care of."""

    slug: str
    name: str
    url: str
    private: bool = True
    backend: str
    state: str = "created"  # "created" or "seeded"
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    seeded_at: str | None = None

    def mark_seeded(self) -> "RepoRecord":
        """Return a copy advanced to the ``seeded`` state."""
        return self.model_copy(
            update={
                "state": SeedOutcome.SEEDED.value,
                "seeded_at": datetime.now(UTC).isoformat(),
            }
        )


class RepoManifest:
    """JSON-file manifest of created repositories, safe to share across runs."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._repos: dict[str, RepoRecord] | None = None

    def _load(self) -> dict[str, RepoRecord]:
        if self._repos is not None:
            return self._repos
        if not self.path.is_file():
            self._repos = {}
            return self._repos
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ManifestCorruptError(
                f"manifest {self.path} is unreadable ({exc}); repair or delete it"
            ) from exc
        repos = raw.get("repos", {}) if isinstance(raw, dict) else {}
        self._repos = {slug: RepoRecord.model_validate(entry) for slug, entry in repos.items()}
        return self._repos

    def get(self, slug: str) -> RepoRecord | None:
        """Return the record for ``slug``, or None if this slug is new."""
        return self._load().get(slug)

    def put(self, record: RepoRecord) -> None:
        """Persist one record with an atomic file swap."""
        repos = self._load()
        repos[record.slug] = record
        payload = {"version": MANIFEST_VERSION, "repos": {
            slug: entry.model_dump(mode="json") for slug, entry in repos.items()
        }}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as tmp_file:
                tmp_file.write(json.dumps(payload, indent=2, sort_keys=True))
            os.replace(tmp_path, self.path)
        except BaseException:
            Path(tmp_path).unlink(missing_ok=True)
            raise
