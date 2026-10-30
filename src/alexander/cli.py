"""Alexander CLI: a command group wiring the discovery, ranking, and builder stages."""

import click

from alexander.discovery import discover_events


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
