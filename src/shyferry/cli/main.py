from __future__ import annotations

import typer

app = typer.Typer(help="Move files between cloud storage providers, verified.")


@app.command()
def version() -> None:
    """Print the installed version."""
    from importlib.metadata import version as _version

    typer.echo(_version("shyferry"))
