"""Alexander CLI: a command group wiring the discovery, ranking, and builder stages."""

import asyncio
import json
from datetime import timedelta
from functools import partial
from pathlib import Path

import click
from pydantic import ValidationError

from alexander.builder import (
    BuildBudgets,
    BuildStatus,
    HackathonBrief,
    MissingApiKeyError,
    create_builder,
)
from alexander.discovery import discover_events
from alexander.orchestrator import plan_run
from alexander.ranking import (
    InterestProfile,
    RankedEvent,
    load_profile,
    rank_events,
    resolve_profile_path,
)
from alexander.swarm import DEFAULT_REGISTRY_PATH, ClaimRegistry, SwarmOutcome, run_swarm


@click.group()
def cli() -> None:
    """Alexander the Cracked: find hackathons, rank them, and build projects."""


@cli.command()
@click.option("--no-cache", is_flag=True, default=False, help="Bypass the on-disk response cache.")
def discover(no_cache: bool) -> None:
    """Search public feeds for hackathons and competitions."""
    events = discover_events(use_cache=not no_cache)
    click.echo(f"Found {len(events)} events:")
    for event in events:
        click.echo(f"- {event.name} [{event.source}] {event.url}")


@cli.command()
@click.option("--no-cache", is_flag=True, default=False, help="Bypass the on-disk response cache.")
@click.option(
    "--profile",
    "profile_path",
    type=click.Path(path_type=Path),
    default=None,
    help="Path to a profile YAML file (default: profile.yaml or ~/.config/alexander/profile.yaml).",
)
@click.option("--json", "as_json", is_flag=True, default=False, help="Emit machine-readable JSON.")
def rank(no_cache: bool, profile_path: Path | None, as_json: bool) -> None:
    """Rank discovered events against your interest profile."""
    profile = _load_profile(profile_path)
    events = discover_events(use_cache=not no_cache)
    ranked = rank_events(events, profile)
    if as_json:
        click.echo(json.dumps(_ranked_to_json(ranked), indent=2))
        return
    if not ranked:
        click.echo("No upcoming events to rank. Run `alexander discover` to check the feeds.")
        return
    click.echo(
        f"{'Rank':>4}  {'Score':>5}  {'Name':<30}  {'Deadline':<19}  "
        f"{'Prize':<12}  Top reason"
    )
    for position, entry in enumerate(ranked, start=1):
        deadline = entry.event.deadline.strftime("%Y-%m-%d %H:%M") if entry.event.deadline else "—"
        prize = entry.event.prize_amount or "—"
        top_reason = entry.reasons[0] if entry.reasons else "—"
        click.echo(
            f"{position:>4}  {entry.score:>5.1f}  {entry.event.name[:30]:<30}  "
            f"{deadline:<19}  {prize[:12]:<12}  {top_reason}"
        )


def _load_profile(profile_path: Path | None) -> InterestProfile:
    """Resolve and load the interest profile, with friendly CLI errors."""
    resolved = resolve_profile_path(profile_path)
    if resolved is None:
        raise click.UsageError(
            "No profile found. Create a profile.yaml (see the shipped example) "
            "or pass --profile <path>."
        )
    try:
        return load_profile(resolved)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc


def _ranked_to_json(ranked: list[RankedEvent]) -> list[dict[str, object]]:
    """Serialize ranked events for --json output."""
    return [
        {
            "rank": position,
            "score": entry.score,
            "reasons": entry.reasons,
            "event": entry.event.model_dump(mode="json"),
        }
        for position, entry in enumerate(ranked, start=1)
    ]


@cli.command()
@click.option("--brief", "brief_file", required=True, type=click.Path(exists=True, path_type=Path))
@click.option("--out", "out_dir", required=True, type=click.Path(path_type=Path))
@click.option("--max-attempts", default=5, show_default=True, type=click.IntRange(min=1))
@click.option("--minutes", default=30.0, show_default=True, type=click.FloatRange(min=0))
def build(brief_file: Path, out_dir: Path, max_attempts: int, minutes: float) -> None:
    """Build a project from a JSON hackathon brief."""
    try:
        brief = HackathonBrief.model_validate_json(brief_file.read_text(encoding="utf-8"))
    except ValidationError as exc:
        click.echo(f"Brief file {brief_file} is not a valid brief: {exc}", err=True)
        raise SystemExit(1) from exc
    try:
        budgets = BuildBudgets(max_attempts=max_attempts, wall_clock=timedelta(minutes=minutes))
        result = asyncio.run(create_builder().build(brief, out_dir, budgets))
    except MissingApiKeyError as exc:
        click.echo(str(exc), err=True)
        raise SystemExit(1) from exc
    except ValueError as exc:
        click.echo(f"Invalid build budgets: {exc}", err=True)
        raise SystemExit(1) from exc

    click.echo(f"build {result.status.value}: {result.artifact_path}")
    if result.test_summary:
        click.echo(f"tests: {result.test_summary}")
    if result.error:
        click.echo(f"error: {result.error}", err=True)
    if result.status is not BuildStatus.SUCCESS:
        raise SystemExit(1)


@cli.command()
@click.option("--no-cache", is_flag=True, default=False, help="Bypass the on-disk response cache.")
@click.option(
    "--profile",
    "profile_path",
    type=click.Path(path_type=Path),
    default=None,
    help="Path to a profile YAML file (default: profile.yaml or ~/.config/alexander/profile.yaml).",
)
@click.option(
    "--top",
    default=None,
    type=click.IntRange(min=1),
    help="Build for the top N ranked events (default: the single top event).",
)
@click.option(
    "--pick",
    default=None,
    type=click.IntRange(min=1),
    help="Build for the event at this 1-based rank (matching `alexander rank` output).",
)
@click.option(
    "--out",
    "out_root",
    type=click.Path(path_type=Path),
    default=Path("builds"),
    show_default=True,
    help="Root directory for generated projects.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Stop before building and print what would be built.",
)
@click.option(
    "--backend",
    default=None,
    help="Build backend override (default: ALEXANDER_BUILD_BACKEND or 'obvious').",
)
@click.option("--max-attempts", default=5, show_default=True, type=click.IntRange(min=1))
@click.option("--minutes", default=30.0, show_default=True, type=click.FloatRange(min=0))
def run(
    no_cache: bool,
    profile_path: Path | None,
    top: int | None,
    pick: int | None,
    out_root: Path,
    dry_run: bool,
    backend: str | None,
    max_attempts: int,
    minutes: float,
) -> None:
    """Run the full pipeline: discover, rank, and build for the top event(s)."""
    profile = _load_profile(profile_path)
    events = discover_events(use_cache=not no_cache)
    ranked = rank_events(events, profile)
    if not ranked:
        click.echo("No upcoming events to build for. Check back once the feeds refresh.")
        return
    try:
        plans = plan_run(ranked, out_root, top=top, pick=pick)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(f"Discovered {len(events)} event(s), {len(ranked)} upcoming. Building for:")
    for position, plan in enumerate(plans, start=1):
        click.echo(
            f"  {position if pick is None else pick}. {plan.event.name} [{plan.event.source}] "
            f"-> {plan.out_dir}"
        )
    if dry_run:
        click.echo("Dry run: no builds executed.")
        return

    try:
        budgets = BuildBudgets(max_attempts=max_attempts, wall_clock=timedelta(minutes=minutes))
        builder = create_builder(backend)
    except MissingApiKeyError as exc:
        click.echo(str(exc), err=True)
        raise SystemExit(1) from exc
    except ValueError as exc:
        click.echo(f"Invalid build configuration: {exc}", err=True)
        raise SystemExit(1) from exc

    failed = False
    for plan in plans:
        click.echo(f"Building {plan.event.name} into {plan.out_dir} ...")
        result = asyncio.run(builder.build(plan.brief, plan.out_dir, budgets))
        click.echo(f"build {result.status.value}: {result.artifact_path}")
        if result.test_summary:
            click.echo(f"tests: {result.test_summary}")
        if result.error:
            click.echo(f"error: {result.error}", err=True)
        if result.status is not BuildStatus.SUCCESS:
            failed = True
    if failed:
        raise SystemExit(1)


def _print_outcome(outcome: SwarmOutcome) -> None:
    """Echo one finished swarm build as its worker completes it."""
    result = outcome.result
    click.echo(f"[w{outcome.worker_id}] build {result.status.value}: {result.artifact_path}")
    if result.test_summary:
        click.echo(f"[w{outcome.worker_id}] tests: {result.test_summary}")
    if result.error:
        click.echo(f"[w{outcome.worker_id}] error: {result.error}", err=True)


def _print_registry_state(registry_path: Path) -> None:
    """Summarize the shared registry without creating it (dry runs read only)."""
    if not registry_path.exists():
        click.echo("Registry: no claims recorded yet.")
        return
    snapshot = ClaimRegistry(registry_path)
    try:
        rows = snapshot.results()
    finally:
        snapshot.close()
    pending = [row.event_slug for row in rows if row.status == "claimed"]
    click.echo(f"Registry: {len(rows)} claim(s) on record, {len(pending)} still pending.")


@cli.command()
@click.option("--no-cache", is_flag=True, default=False, help="Bypass the on-disk response cache.")
@click.option(
    "--profile",
    "profile_path",
    type=click.Path(path_type=Path),
    default=None,
    help="Path to a profile YAML file (default: profile.yaml or ~/.config/alexander/profile.yaml).",
)
@click.option(
    "--instances",
    default=3,
    show_default=True,
    type=click.IntRange(min=1),
    help="Number of concurrent swarm workers.",
)
@click.option(
    "--events",
    "event_count",
    default=None,
    type=click.IntRange(min=1),
    help="Plan the top M ranked events (default: one per worker).",
)
@click.option(
    "--out",
    "out_root",
    type=click.Path(path_type=Path),
    default=Path("builds"),
    show_default=True,
    help="Root directory for generated projects.",
)
@click.option(
    "--registry",
    "registry_path",
    type=click.Path(path_type=Path),
    default=DEFAULT_REGISTRY_PATH,
    show_default=True,
    help="Path to the shared SQLite claim registry.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Print the plan and registry state; claim and build nothing.",
)
@click.option(
    "--backend",
    default=None,
    help="Build backend override (default: ALEXANDER_BUILD_BACKEND or 'obvious').",
)
@click.option("--max-attempts", default=5, show_default=True, type=click.IntRange(min=1))
@click.option("--minutes", default=30.0, show_default=True, type=click.FloatRange(min=0))
def swarm(
    no_cache: bool,
    profile_path: Path | None,
    instances: int,
    event_count: int | None,
    out_root: Path,
    registry_path: Path,
    dry_run: bool,
    backend: str | None,
    max_attempts: int,
    minutes: float,
) -> None:
    """Discover and rank once, then build the top events concurrently."""
    profile = _load_profile(profile_path)
    events = discover_events(use_cache=not no_cache)
    ranked = rank_events(events, profile)
    if not ranked:
        click.echo("No upcoming events to build for. Check back once the feeds refresh.")
        return
    # One event per worker keeps the default swarm meaningful (--instances 3
    # plans 3 events) while --events sizes the pool independently.
    pool_size = event_count if event_count is not None else instances
    plans = plan_run(ranked, out_root, top=pool_size)

    click.echo(
        f"Discovered {len(events)} event(s), {len(ranked)} upcoming. "
        f"Swarm plan ({instances} workers):"
    )
    for position, plan in enumerate(plans, start=1):
        click.echo(
            f"  {position}. {plan.event.name} [{plan.event.source}] -> {plan.out_dir}"
        )

    if dry_run:
        _print_registry_state(registry_path)
        click.echo("Dry run: nothing claimed, nothing built.")
        return

    budgets_factory = partial(
        BuildBudgets, max_attempts=max_attempts, wall_clock=timedelta(minutes=minutes)
    )
    try:
        budgets_factory()  # validate the budget flags before any worker starts
        builder = create_builder(backend)
        registry = ClaimRegistry(registry_path)
    except MissingApiKeyError as exc:
        click.echo(str(exc), err=True)
        raise SystemExit(1) from exc
    except ValueError as exc:
        click.echo(f"Invalid build configuration: {exc}", err=True)
        raise SystemExit(1) from exc

    try:
        outcomes = asyncio.run(
            run_swarm(
                plans,
                registry=registry,
                builder=builder,
                instances=instances,
                budgets_factory=budgets_factory,
                on_result=_print_outcome,
            )
        )
        pending = registry.pending()
    except MissingApiKeyError as exc:
        click.echo(str(exc), err=True)
        raise SystemExit(1) from exc
    finally:
        registry.close()

    failed = [outcome for outcome in outcomes if outcome.result.status is not BuildStatus.SUCCESS]
    click.echo(f"Swarm complete: {len(outcomes) - len(failed)} succeeded, {len(failed)} failed.")
    if pending:
        click.echo(
            f"Warning: {len(pending)} pending claim(s) belong to other or unfinished runs: "
            f"{', '.join(pending)}"
        )
    if failed:
        raise SystemExit(1)
