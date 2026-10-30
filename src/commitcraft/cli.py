"""Typer command-line interface for CommitCraft."""

import os
from pathlib import Path
import sys
from typing import Optional
import typer
from rich.console import Console
from rich.prompt import Confirm, Prompt
from rich.table import Table

from commitcraft.config import AppConfig, REQUIRED_MODEL
from commitcraft.dependencies import DependencyResolver
from commitcraft.diff_parser import DiffParser
from commitcraft.errors import (
    CommitCraftError,
    ModelUnavailableError,
    PlanValidationError,
    StaleSnapshotError,
)
from commitcraft.executor import PlanExecutor
from commitcraft.hooks import HookManager
from commitcraft.model_client import OllamaClient
from commitcraft.planner import SemanticPlanner
from commitcraft.pr_description import PRDescriptionGenerator
from commitcraft.repository import RepositoryInspector
from commitcraft.review import PlanEditor, ReviewUI
from commitcraft.snapshot import SnapshotEngine


app = typer.Typer(
    name="commitcraft",
    help="Turn a messy Git working tree into logical, reviewable commits with local AI.",
    no_args_is_help=True,
)
console = Console()

hook_app = typer.Typer(help="Manage optional CommitCraft advisory Git hooks.")
app.add_typer(hook_app, name="hook")


@app.callback()
def main_callback() -> None:
    """CommitCraft: Logical, reviewable commits with local AI."""
    pass


@app.command()
def inspect(
    repo_path: Optional[str] = typer.Option(
        None, "--repo", "-r", help="Path to Git repository (defaults to current directory)"
    ),
) -> None:
    """Inspect repository status, working changes, and Ollama model connectivity."""
    target_dir = Path(repo_path) if repo_path else Path.cwd()
    config = AppConfig.load()

    console.print("[bold cyan]CommitCraft Diagnostic Inspection[/bold cyan]\n")

    # 1. Repository inspection
    try:
        inspector = RepositoryInspector(target_dir)
        repo, runner, state = inspector.inspect()
        console.print(f"[bold green]✔[/bold green] Repository Root: [white]{state.root_dir}[/white]")
        console.print(f"[bold green]✔[/bold green] Active Branch:   [cyan]{state.branch_name}[/cyan] ({state.branch_ref})")
        console.print(f"[bold green]✔[/bold green] HEAD Commit:     [yellow]{state.head_commit[:8]}[/yellow]")

        status_table = Table(title="Working Tree Changes", box=None)
        status_table.add_column("Category", style="bold")
        status_table.add_column("Files", justify="left")

        status_table.add_row("Staged", f"{len(state.staged_files)}: {', '.join(state.staged_files[:5]) or 'None'}")
        status_table.add_row("Unstaged", f"{len(state.unstaged_files)}: {', '.join(state.unstaged_files[:5]) or 'None'}")
        status_table.add_row("Untracked", f"{len(state.untracked_files)}: {', '.join(state.untracked_files[:5]) or 'None'}")
        console.print(status_table)

    except CommitCraftError as e:
        console.print(f"[bold red]✘ Repository check failed:[/bold red] {e}")
        raise typer.Exit(code=1)

    # 2. Ollama & model inspection
    console.print("\n[bold cyan]Ollama Runtime Status[/bold cyan]")
    client = OllamaClient(
        base_url=config.ollama_base_url,
        connect_timeout=config.connect_timeout,
        read_timeout=config.read_timeout,
    )
    try:
        client.check_health()
        console.print(f"[bold green]✔[/bold green] Endpoint: [white]{config.ollama_base_url}[/white] (Connected)")
        console.print(f"[bold green]✔[/bold green] Required Model: [cyan]{REQUIRED_MODEL}[/cyan] (Available)")
    except ModelUnavailableError as e:
        console.print(f"[bold red]✘ Ollama unavailable:[/bold red] {e}")
        if e.resolution:
            console.print(f"  [yellow]-> {e.resolution}[/yellow]")
        raise typer.Exit(code=1)


@app.command(name="config")
def config_cmd(
    url: Optional[str] = typer.Option(None, "--url", help="Set Ollama base URL"),
    timeout: Optional[float] = typer.Option(None, "--timeout", help="Set inference read timeout in seconds"),
) -> None:
    """View and update CommitCraft configuration."""
    cfg = AppConfig.load()
    updated = False

    if url:
        cfg.ollama_base_url = url
        updated = True
    if timeout:
        cfg.read_timeout = timeout
        updated = True

    if updated:
        save_path = cfg.save()
        console.print(f"[bold green]✔ Configuration saved to {save_path}[/bold green]")

    console.print("\n[bold cyan]Current Configuration:[/bold cyan]")
    console.print(f"  Ollama URL:       [white]{cfg.ollama_base_url}[/white]")
    console.print(f"  Required Model:   [cyan]{cfg.model}[/cyan] [dim](Mandatory, no substitution)[/dim]")
    console.print(f"  Connect Timeout:  [white]{cfg.connect_timeout}s[/white]")
    console.print(f"  Read Timeout:     [white]{cfg.read_timeout}s[/white]")
    console.print(f"  Max Corrections:  [white]{cfg.max_correction_attempts}[/white]")


@hook_app.command("install")
def hook_install(
    repo_path: Optional[str] = typer.Option(None, "--repo", "-r", help="Path to Git repository"),
) -> None:
    """Install optional CommitCraft advisory pre-commit hook."""
    inspector = RepositoryInspector(Path(repo_path) if repo_path else Path.cwd())
    root = inspector.discover_root()
    mgr = HookManager(root / ".git")
    hook_file = mgr.install()
    console.print(f"[bold green]✔ Advisory Git pre-commit hook installed at {hook_file}[/bold green]")


@hook_app.command("remove")
def hook_remove(
    repo_path: Optional[str] = typer.Option(None, "--repo", "-r", help="Path to Git repository"),
) -> None:
    """Remove CommitCraft advisory pre-commit hook."""
    inspector = RepositoryInspector(Path(repo_path) if repo_path else Path.cwd())
    root = inspector.discover_root()
    mgr = HookManager(root / ".git")
    if mgr.remove():
        console.print("[bold green]✔ Advisory Git pre-commit hook removed.[/bold green]")
    else:
        console.print("[yellow]No CommitCraft pre-commit hook was found.[/yellow]")


@app.command()
def split(
    repo_path: Optional[str] = typer.Option(
        None, "--repo", "-r", help="Path to Git repository (defaults to current directory)"
    ),
    auto_approve: bool = typer.Option(
        False, "--yes", "-y", help="Approve execution immediately if preflight succeeds (testing only)"
    ),
    custom_pr_path: Optional[str] = typer.Option(
        None, "--pr-output", help="Optional custom path for generated PR markdown"
    ),
) -> None:
    """Analyze working tree and interactively split into logical commits."""
    target_dir = Path(repo_path) if repo_path else Path.cwd()
    app_config = AppConfig.load()
    ui = ReviewUI(console)

    console.print("[bold cyan]══════════════ COMMITCRAFT SPLIT ══════════════[/bold cyan]\n")

    # 1. Repository inspection
    try:
        inspector = RepositoryInspector(target_dir)
        repo, runner, state = inspector.inspect()
    except CommitCraftError as e:
        console.print(f"[bold red]Repository error:[/bold red] {e}")
        raise typer.Exit(code=1)

    # 2. Target snapshot capture
    snapshot_engine = SnapshotEngine(repo, runner, state)
    try:
        with console.status("[cyan]Capturing target snapshot using isolated index...[/cyan]"):
            snapshot = snapshot_engine.capture_snapshot()
    except CommitCraftError as e:
        console.print(f"[bold red]Snapshot error:[/bold red] {e}")
        raise typer.Exit(code=1)

    if not snapshot.has_changes:
        console.print("[bold green]Working tree is clean. Nothing to commit or split.[/bold green]")
        raise typer.Exit(code=0)

    # 3. Diff extraction and Change-Unit construction
    units = DiffParser.parse(snapshot.diff_text)
    if not units:
        console.print("[yellow]No parseable change units found.[/yellow]")
        raise typer.Exit(code=0)

    console.print(f"Extracted [bold green]{len(units)}[/bold green] change unit(s) across target changes.")

    # 4. Mandatory Ollama AI planner
    ollama_client = OllamaClient(
        base_url=app_config.ollama_base_url,
        connect_timeout=app_config.connect_timeout,
        read_timeout=app_config.read_timeout,
    )
    planner = SemanticPlanner(ollama_client, max_corrections=app_config.max_correction_attempts)

    try:
        with console.status(f"[cyan]Requesting semantic plan from {REQUIRED_MODEL} via Ollama...[/cyan]"):
            plan = planner.plan(units)
    except CommitCraftError as e:
        console.print(f"\n[bold red]AI Planning Failed:[/bold red] {e}")
        console.print("[yellow]CommitCraft requires a valid plan from the local model to proceed. Aborting.[/yellow]")
        raise typer.Exit(code=1)

    executor = PlanExecutor(repo, runner, snapshot_engine)

    # 5. Interactive review and editing loop
    while True:
        try:
            ordered_groups = DependencyResolver.resolve_order(plan.groups)
        except Exception as e:
            ordered_groups = plan.groups

        preflight = executor.preflight_replay(ordered_groups, units, snapshot)
        ui.display_plan(plan, units, preflight)

        if auto_approve:
            if not preflight.tree_equality:
                console.print(f"[bold red]Preflight failed: {preflight.error_message}[/bold red]")
                raise typer.Exit(code=1)
            confirmed = True
            break

        # Menu options
        console.print("\n[bold]Options:[/bold]")
        console.print("  [1] Approve & Execute commits")
        console.print("  [2] Move a unit between groups")
        console.print("  [3] Merge two groups")
        console.print("  [4] Split a group")
        console.print("  [5] Edit group commit message")
        console.print("  [6] Edit group dependencies")
        console.print("  [7] Request fresh AI proposal")
        console.print("  [0] Abort")

        choice = Prompt.ask("\nEnter choice", choices=["1", "2", "3", "4", "5", "6", "7", "0"], default="1")

        if choice == "0":
            console.print("[yellow]Operation aborted by user. Working tree and branch untouched.[/yellow]")
            raise typer.Exit(code=0)

        elif choice == "1":
            if not preflight.tree_equality:
                console.print(f"[bold red]Cannot execute: Preflight failed ({preflight.error_message}). Fix plan first.[/bold red]")
                continue

            # Section 9.6: Require explicit confirmation, default to declining
            confirmed = Confirm.ask(
                f"\nAre you sure you want to install {len(ordered_groups)} commit(s) on branch '{state.branch_name}'?",
                default=False,
            )
            if confirmed:
                break
            else:
                console.print("[yellow]Execution cancelled. Returning to plan menu.[/yellow]")

        elif choice == "2":
            uid = Prompt.ask("Unit ID to move (e.g. U001)")
            from_g = Prompt.ask("Source Group ID (e.g. G01)")
            to_g = Prompt.ask("Target Group ID (e.g. G02)")
            try:
                plan = PlanEditor.move_unit(plan, uid, from_g, to_g, units)
                console.print("[green]Unit moved successfully.[/green]")
            except PlanValidationError as e:
                console.print(f"[bold red]Edit rejected:[/bold red] {e}")

        elif choice == "3":
            src = Prompt.ask("Source Group ID to merge from (e.g. G02)")
            tgt = Prompt.ask("Target Group ID to merge into (e.g. G01)")
            try:
                plan = PlanEditor.merge_groups(plan, src, tgt, units)
                console.print("[green]Groups merged successfully.[/green]")
            except PlanValidationError as e:
                console.print(f"[bold red]Merge rejected:[/bold red] {e}")

        elif choice == "4":
            grp = Prompt.ask("Group ID to split (e.g. G01)")
            new_id = Prompt.ask("New Group ID (e.g. G03)")
            uids_str = Prompt.ask("Unit IDs for new group (comma-separated, e.g. U002, U003)")
            uids = [u.strip() for u in uids_str.split(",") if u.strip()]
            new_title = Prompt.ask("New group title")
            new_type = Prompt.ask("Conventional commit type (feat, fix, refactor, test, docs, etc.)", default="feat")
            new_msg = Prompt.ask("Commit message (e.g. 'feat: new feature')")
            try:
                plan = PlanEditor.split_group(plan, grp, new_id, uids, new_title, new_msg, new_type, units)
                console.print("[green]Group split successfully.[/green]")
            except PlanValidationError as e:
                console.print(f"[bold red]Split rejected:[/bold red] {e}")

        elif choice == "5":
            grp = Prompt.ask("Group ID to edit (e.g. G01)")
            new_msg = Prompt.ask("New Conventional Commit message")
            try:
                plan = PlanEditor.edit_message(plan, grp, new_msg, units)
                console.print("[green]Commit message updated successfully.[/green]")
            except PlanValidationError as e:
                console.print(f"[bold red]Edit rejected:[/bold red] {e}")

        elif choice == "6":
            grp = Prompt.ask("Group ID to update dependencies for (e.g. G02)")
            deps_str = Prompt.ask("Prerequisite group IDs (comma-separated, or empty for none)", default="")
            deps = [d.strip() for d in deps_str.split(",") if d.strip()]
            try:
                plan = PlanEditor.set_dependencies(plan, grp, deps, units)
                console.print("[green]Dependencies updated successfully.[/green]")
            except PlanValidationError as e:
                console.print(f"[bold red]Update rejected:[/bold red] {e}")

        elif choice == "7":
            with console.status(f"[cyan]Requesting fresh proposal from {REQUIRED_MODEL}...[/cyan]"):
                try:
                    plan = planner.plan(units)
                    console.print("[green]Fresh plan generated from local AI model.[/green]")
                except CommitCraftError as e:
                    console.print(f"[bold red]AI Planning Failed:[/bold red] {e}")

    # 6. Execute commit construction and guarded branch update
    try:
        with console.status("[cyan]Creating Git commit objects and updating branch...[/cyan]"):
            exec_res = executor.execute(preflight, snapshot, approval_confirmed=True)
    except CommitCraftError as e:
        console.print(f"\n[bold red]Execution error:[/bold red] {e}")
        raise typer.Exit(code=1)

    console.print("\n[bold green]══════════════ EXECUTION COMPLETE ══════════════[/bold green]")
    console.print(f"[bold]Branch:[/bold] [cyan]{exec_res.branch_ref}[/cyan]")
    console.print(f"[bold]New HEAD:[/bold] [yellow]{exec_res.new_head[:8]}[/yellow]")
    console.print(f"[bold]Verified Tree:[/bold] [green]{exec_res.final_tree[:8]}[/green] [dim](Matches exact snapshot)[/dim]\n")

    for idx, (commit_sha, grp) in enumerate(zip(exec_res.created_commits, exec_res.ordered_groups), 1):
        console.print(f"  [{idx}/{len(exec_res.created_commits)}] [yellow]{commit_sha[:8]}[/yellow] {grp.message}")

    # 7. Generate editable PR description
    pr_md = PRDescriptionGenerator.generate_markdown(plan, exec_res, units)
    pr_path = PRDescriptionGenerator.save_pr_description(
        pr_md,
        git_dir=Path(repo.git_dir),
        custom_path=Path(custom_pr_path) if custom_pr_path else None,
    )
    console.print(f"\n[bold green]✔ PR Description generated and saved to:[/bold green] [white]{pr_path}[/white]")


if __name__ == "__main__":
    app()
