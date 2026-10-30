"""Idempotency guarantees of ensure_repo / seed_repo, fixture-first."""

import pytest

from alexander.repos.creator import FixtureRepoCreator, SeedRefusedError
from alexander.repos.manifest import RepoManifest
from alexander.repos.models import CreateOutcome, RemoteIdentity, RepoSpec, SeedOutcome
from alexander.repos.service import ensure_repo, seed_repo


def make_spec(slug: str = "demo-event", source=None) -> RepoSpec:
    return RepoSpec(
        slug=slug, name=slug, description="test", private=True, source_dir=source
    )


@pytest.fixture
def creator() -> FixtureRepoCreator:
    return FixtureRepoCreator()


@pytest.fixture
def manifest(tmp_path) -> RepoManifest:
    return RepoManifest(tmp_path / "manifest.json")


def test_create_then_rerun_is_manifest_hit(creator, manifest):
    first = ensure_repo(make_spec(), creator, manifest)
    assert first.outcome is CreateOutcome.CREATED

    second = ensure_repo(make_spec(), creator, manifest)
    assert second.outcome is CreateOutcome.MANIFEST_HIT
    assert second.url == first.url
    assert creator.create_calls == ["demo-event"]  # backend touched exactly once


def test_distinct_slugs_never_collide(creator, manifest):
    first = ensure_repo(make_spec("event-a"), creator, manifest)
    second = ensure_repo(make_spec("event-b"), creator, manifest)
    assert first.url != second.url
    assert len(creator.repos) == 2


def test_crash_window_heals_without_duplicate(creator, manifest):
    """A run died after remote create but before the manifest write.

    The next run must adopt the existing repo (EXISTS), not make a second.
    """
    crashed = creator.create(make_spec())  # simulate: remote created, not recorded
    assert crashed.outcome is CreateOutcome.CREATED
    assert manifest.get("demo-event") is None

    healed = ensure_repo(make_spec(), creator, manifest)
    assert healed.outcome is CreateOutcome.EXISTS
    assert healed.url == crashed.identity.url
    assert len(creator.repos) == 1  # exactly one remote repo exists


def test_healed_state_is_durable(creator, manifest):
    creator.create(make_spec())  # crash window
    ensure_repo(make_spec(), creator, manifest)
    rerun = ensure_repo(make_spec(), creator, manifest)
    assert rerun.outcome is CreateOutcome.MANIFEST_HIT
    assert len(creator.create_calls) == 2  # one crashed, one heal; never a third


def test_seed_pushes_once_then_skips(creator, manifest, tmp_path):
    source = tmp_path / "build"
    source.mkdir()
    (source / "README.md").write_text("built project")

    spec = make_spec(source=source)
    result = ensure_repo(spec, creator, manifest)
    identity = RemoteIdentity(owner="o", url=result.url)

    seeded = seed_repo(spec, creator, manifest, identity)
    assert seeded.outcome is SeedOutcome.SEEDED

    again = seed_repo(spec, creator, manifest, identity)
    assert again.outcome is SeedOutcome.SKIPPED
    assert len(creator.seed_calls) == 1


def test_seed_refused_leaves_record_unseeded(creator, manifest, tmp_path):
    spec = make_spec(source=tmp_path / "build")
    result = ensure_repo(spec, creator, manifest)
    identity = RemoteIdentity(owner="o", url=result.url)
    creator.non_empty.add("demo-event")  # fixture simulates a non-empty remote

    refused = seed_repo(spec, creator, manifest, identity)
    assert refused.outcome is SeedOutcome.REFUSED
    record = manifest.get("demo-event")
    assert record.state == "created"  # never advanced past created


def test_seed_without_source_is_skipped(creator, manifest):
    spec = make_spec(source=None)
    result = ensure_repo(spec, creator, manifest)
    identity = RemoteIdentity(owner="o", url=result.url)
    skipped = seed_repo(spec, creator, manifest, identity)
    assert skipped.outcome is SeedOutcome.SKIPPED
    assert creator.seed_calls == []


def test_seed_without_record_is_an_error(creator, manifest):
    with pytest.raises(ValueError, match="ensure_repo first"):
        seed_repo(make_spec(source="x"), creator, manifest, RemoteIdentity(owner="o", url="u"))


def test_fixture_backend_raises_refusal_directly(creator):
    creator.non_empty.add("demo-event")
    spec = make_spec(source="x")
    with pytest.raises(SeedRefusedError):
        creator.seed(spec, RemoteIdentity(owner="o", url="u"))
