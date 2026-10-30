"""CLI entry point for CommitCraft."""

from typing import Optional
import typer

app = typer.Typer(
    name="commitcraft",
    help="Turn a messy Git working tree into logical, reviewable commits with local AI.",
    no_args_is_help=True,
)


@app.callback()
def main_callback() -> None:
    """CommitCraft: Logical, reviewable commits with local AI."""
    pass


@app.command()
def split(
    repo_path: Optional[str] = typer.Option(
        None, "--repo", "-r", help="Path to Git repository (defaults to current directory)"
    ),
) -> None:
    """Analyze working tree and interactively split into logical commits."""
    typer.echo("CommitCraft split workflow")


@app.command()
def inspect(
    repo_path: Optional[str] = typer.Option(
        None, "--repo", "-r", help="Path to Git repository (defaults to current directory)"
    ),
) -> None:
    """Inspect repository state and Ollama model status."""
    typer.echo("CommitCraft inspect")


@app.command()
def config() -> None:
    """View and update CommitCraft configuration."""
    typer.echo("CommitCraft config")


if __name__ == "__main__":
    app()
