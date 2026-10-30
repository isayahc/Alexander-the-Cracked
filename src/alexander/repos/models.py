"""Value types and pure rules for idempotent repository creation."""

import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from urllib.parse import urlparse

# GitHub repository-name rules: letters, digits, hyphen, underscore, dot;
# must not start with a dot or hyphen and must not end in ``.git``.
_REPO_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_REPO_NAME_MAX_LEN = 100


class RepoNameError(ValueError):
    """The requested repository name is not acceptable to GitHub."""


def validate_repo_name(name: str) -> str:
    """Return ``name`` if GitHub-acceptable, else raise :class:`RepoNameError`."""
    if not name or len(name) > _REPO_NAME_MAX_LEN:
        raise RepoNameError(
            f"repository name must be 1-{_REPO_NAME_MAX_LEN} characters: {name!r}"
        )
    if name.endswith(".git"):
        raise RepoNameError(f"repository name must not end in '.git': {name!r}")
    if not _REPO_NAME_RE.match(name):
        raise RepoNameError(
            f"repository name may only contain letters, digits, '.', '_' and '-',"
            f" and must not start with '.' or '-': {name!r}"
        )
    return name


def repo_name_from_slug(slug: str) -> str:
    """Derive a valid GitHub repo name from an event slug.

    Slugs are already filesystem-safe, but ``validate_repo_name`` is stricter
    than the pipeline's slug rule, so re-check rather than assume.
    """
    return validate_repo_name(slug)


@dataclass(frozen=True)
class RepoSpec:
    """What to create: the idempotency key, the remote name, and an optional seed."""

    slug: str
    name: str
    description: str = ""
    private: bool = True
    source_dir: Path | None = None


class CreateOutcome(StrEnum):
    """How one ``ensure_repo`` call resolved."""

    CREATED = "created"
    EXISTS = "exists"
    MANIFEST_HIT = "manifest-hit"


class SeedOutcome(StrEnum):
    """How one ``seed_repo`` call resolved."""

    SEEDED = "seeded"
    SKIPPED = "skipped"
    REFUSED = "refused"


@dataclass(frozen=True)
class RemoteIdentity:
    """A repository the backend can see on the remote."""

    owner: str
    url: str


def owner_from_url(url: str) -> str:
    """Best-effort owner extraction from a repository URL ("owner" segment)."""
    parts = urlparse(url).path.strip("/").split("/")
    return parts[0] if parts and parts[0] else "unknown"
