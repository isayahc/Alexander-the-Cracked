"""Alexander CLI: a command group wiring the discovery, ranking, and builder stages."""

import click


@click.group()
def cli() -> None:
    """Alexander the Cracked: find hackathons, rank them, and build projects."""


@cli.command()
def discover() -> None:
    """Search public feeds for hackathons and competitions."""
    click.echo("not implemented yet")
