"""Idempotent ensure/seed operations over a creator backend and a manifest.

Every rule here is about one thing: calling the same operation twice must
leave exactly one repository in the same state as calling it once.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from alexander.repos.creator import RepoCreator, SeedRefusedError
from alexander.repos.manifest import RepoManifest, RepoRecord
from alexander.repos.models import (
    CreateOutcome,
    RemoteIdentity,
    RepoSpec,
    SeedOutcome,
)


@dataclass(frozen=True)
class EnsureResult:
    """The outcome of one idempotent ensure call, including the durable record."""

    slug: str
    url: str
    outcome: CreateOutcome
    record: RepoRecord


@dataclass(frozen=True)
class SeedResult:
    """The outcome of one idempotent seed call."""

    slug: str
    outcome: SeedOutcome
    detail: str | None = None


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def ensure_repo(
    spec: RepoSpec, creator: RepoCreator, manifest: RepoManifest
) -> EnsureResult:
    """Make sure the repo exists exactly once, returning its identity.

    Order of resolution:
    1. Manifest hit — the durable record wins; no remote call at all.
    2. Backend create — either ``CREATED`` or ``EXISTS`` (the crash-window
       heal: a previous run died after creating but before recording).
    3. The record is written atomically either way, so the next run hits
       the manifest and touches nothing.
    """
    existing = manifest.get(spec.slug)
    if existing is not None:
        return EnsureResult(
            slug=spec.slug,
            url=existing.url,
            outcome=CreateOutcome.MANIFEST_HIT,
            record=existing,
        )

    reply = creator.create(spec)
    record = RepoRecord(
        slug=spec.slug,
        name=spec.name,
        url=reply.identity.url,
        private=spec.private,
        backend=getattr(creator, "name", "unknown"),
        state="created",
        created_at=_now_iso(),
    )
    manifest.put(record)
    return EnsureResult(
        slug=spec.slug, url=reply.identity.url, outcome=reply.outcome, record=record
    )


def seed_repo(
    spec: RepoSpec, creator: RepoCreator, manifest: RepoManifest, identity: RemoteIdentity
) -> SeedResult:
    """Push initial content once; never overwrite remote history.

    ``SKIPPED`` covers both "nothing to seed" and "already seeded" — a
    re-run with the same spec is a no-op by construction. A refusal from
    the backend (remote not empty) is returned as ``REFUSED`` and leaves
    everything untouched; it is the safe outcome, not a failure.
    """
    record = manifest.get(spec.slug)
    if record is None:
        raise ValueError(f"no manifest record for {spec.slug!r}; run ensure_repo first")
    if spec.source_dir is None or record.state == "seeded":
        return SeedResult(slug=spec.slug, outcome=SeedOutcome.SKIPPED)
    try:
        detail = creator.seed(spec, identity)
    except SeedRefusedError as exc:
        return SeedResult(slug=spec.slug, outcome=SeedOutcome.REFUSED, detail=str(exc))
    manifest.put(record.mark_seeded())
    return SeedResult(slug=spec.slug, outcome=SeedOutcome.SEEDED, detail=detail)
