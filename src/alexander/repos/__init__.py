"""Idempotent repository creation for finished builds.

Retries and re-runs must never duplicate a remote repository or clobber one
that already has content. The guarantee comes from three layers:

1. A durable on-disk manifest keyed by event slug — a hit short-circuits
   before any remote call.
2. A backend that reports ``EXISTS`` instead of failing when the remote
   already has the name, healing the crash window between remote creation
   and the manifest write.
3. Seeding that refuses to touch a remote that is not empty — an initial
   push may happen once or not at all, never twice.
"""

from alexander.repos.creator import (  # noqa: F401
    CreatorError,
    FixtureRepoCreator,
    GhRepoCreator,
    SeedRefusedError,
)
from alexander.repos.manifest import (  # noqa: F401
    ManifestCorruptError,
    RepoManifest,
    default_manifest_path,
)
from alexander.repos.models import (  # noqa: F401
    CreateOutcome,
    RemoteIdentity,
    RepoNameError,
    RepoSpec,
    SeedOutcome,
    owner_from_url,
    repo_name_from_slug,
    validate_repo_name,
)
from alexander.repos.service import EnsureResult, SeedResult, ensure_repo, seed_repo  # noqa: F401

__all__ = [
    "CreateOutcome",
    "CreatorError",
    "EnsureResult",
    "FixtureRepoCreator",
    "GhRepoCreator",
    "RepoManifest",
    "ManifestCorruptError",
    "RemoteIdentity",
    "RepoNameError",
    "RepoSpec",
    "SeedOutcome",
    "SeedRefusedError",
    "SeedResult",
    "default_manifest_path",
    "ensure_repo",
    "owner_from_url",
    "repo_name_from_slug",
    "seed_repo",
    "validate_repo_name",
]
