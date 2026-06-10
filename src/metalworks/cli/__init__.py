"""metalworks CLI entry point.

typer + rich are core dependencies by design: a CLI-first tool whose console
script can crash with ModuleNotFoundError at first touch is fighting its own
product. Subcommands (research, reddit, arctic, discovery, mcp) land in M5.
"""

import typer

import metalworks

app = typer.Typer(
    name="metalworks",
    help="Marketing research and Reddit engagement toolkit.",
    no_args_is_help=True,
)


@app.command()
def version() -> None:
    """Print the installed metalworks version."""
    typer.echo(f"metalworks {metalworks.__version__}")


@app.command()
def doctor() -> None:
    """Check installed extras, keys, and data-source reachability."""
    typer.echo(f"metalworks {metalworks.__version__} (pre-release scaffold)")
    typer.echo("doctor: full checks land with the first vertical (M2).")
