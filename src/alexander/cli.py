"""Alexander CLI: a command group wiring the discovery, ranking, and builder stages."""

import json
from pathlib import Path

import click

from alexander.discovery import discover_events
from alexander.ranking import (
    RankedEvent,
    load_profile,
    rank_events,
    resolve_profile_path,
)


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
    resolved = resolve_profile_path(profile_path)
    if resolved is None:
        raise click.UsageError(
            "No profile found. Create a profile.yaml (see the shipped example) "
            "or pass --profile <path>."
        )
    try:
        profile = load_profile(resolved)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
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
